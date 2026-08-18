"""The text each row is embedded from.

This is the part that can be wrong without anything failing. A vector built
from different text than post-graph-rag builds at query time is as useless as
one from the wrong model, and looks identical in the database. The formulas
below are copied from post_graph_rag 1.5.2 `engine.py`, and these hold them to
it.
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from reindex_embeddings import document_text, entity_text, relation_text


def test_a_document_is_embedded_from_its_text():
    assert document_text({"text": "Item 7. Management's Discussion"}) == \
        "Item 7. Management's Discussion"


def test_a_document_with_no_text_is_not_guessed_at():
    assert document_text({"source": "x"}) is None
    assert document_text({"text": "   "}) is None


def test_an_entity_matches_the_library_formula():
    """`f"{name} ({type}): {description}"` — engine.py line 317."""
    assert entity_text({"name": "TBA securities", "type": "Product",
                        "description": "To-be-announced securities"}) == \
        "TBA securities (Product): To-be-announced securities"


def test_entity_aliases_are_appended_the_way_the_library_appends_them():
    got = entity_text({"name": "TBA", "type": "Product", "description": "d",
                       "aliases": ["TBA securities", "to-be-announced"]})
    assert got == "TBA (Product): d Also known as: TBA securities, to-be-announced."


def test_aliases_stored_as_a_python_repr_are_parsed_not_embedded_verbatim():
    """Older writers stored the repr of a list.

    Embedding "['TBA', 'TBA securities']" verbatim puts the vector somewhere
    unrelated to what the library computes, and nothing about the row shows it.
    """
    got = entity_text({"name": "TBA", "type": "Product", "description": "d",
                       "aliases": "['TBA securities', 'to-be-announced']"})
    assert got == "TBA (Product): d Also known as: TBA securities, to-be-announced."


def test_an_entity_without_a_name_is_left_alone():
    assert entity_text({"description": "orphaned"}) is None


def test_a_relation_matches_the_library_formula():
    """`f"{subject} {predicate} {object}. {description}"` — engine.py line 332."""
    assert relation_text({"description": "Boeing makes the 787."},
                         "Boeing", "manufactures", "787") == \
        "Boeing manufactures 787. Boeing makes the 787."


def test_a_relation_with_no_description_has_no_trailing_space():
    assert relation_text({}, "Boeing", "manufactures", "787") == \
        "Boeing manufactures 787."


def test_a_relation_missing_an_endpoint_is_left_alone():
    """Better an old vector than one built from half a sentence."""
    assert relation_text({"description": "d"}, "", "manufactures", "787") is None
    assert relation_text({"description": "d"}, "Boeing", "manufactures", "") is None
