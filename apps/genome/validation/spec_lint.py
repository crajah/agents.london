"""Cross-document reference lint (BUILD consequent task): rule numbers
collide across the six spec documents (two Rule 6.9a's exist), so a
citation of another document's rule must be DOC-QUALIFIED -- `Rule 4.10`
alone is ambiguous the moment two docs define one.

This reports every unqualified citation whose rule number exists in MORE
THAN ONE document. Run:  python validation/spec_lint.py
Exit code 1 if the count ever EXCEEDS the recorded baseline -- new
ambiguity fails; the historical backlog does not."""
import pathlib
import re
import sys

SPEC = pathlib.Path(__file__).resolve().parents[1] / "spec"
BASELINE = 0     # historical backlog; new ambiguous citations fail CI

DEF_RE = re.compile(r"^\*\*Rule (\d+\.\d+[a-z]?)\*\*", re.M)
CITE_RE = re.compile(
    r"(?<![-\w`(])Rule (\d+\.\d+[a-z]?)(?!['s]*\*\*)")
QUALIFIED_RE = re.compile(
    r"`?[\w-]+-spec(?:\.md)?`?[^.]{0,40}Rule (\d+\.\d+[a-z]?)"
    r"|Rule (\d+\.\d+[a-z]?)[^.]{0,15}`?[\w-]+-spec(?:\.md)?`?")


def main() -> int:
    defined: dict[str, set[str]] = {}
    docs = {p.name: p.read_text() for p in sorted(SPEC.glob("*-spec.md"))}
    for name, text in docs.items():
        for rule in DEF_RE.findall(text):
            defined.setdefault(rule, set()).add(name)
    ambiguous_rules = {r for r, ds in defined.items() if len(ds) > 1}
    hits = []
    for name, text in docs.items():
        lines = text.splitlines()
        for i, line in enumerate(lines, 1):
            # a qualifier may sit at the end of the PREVIOUS line
            window = (lines[i - 2][-60:] + " " if i > 1 else "") + line
            for m in CITE_RE.finditer(line):
                rule = m.group(1)
                if rule not in ambiguous_rules:
                    continue
                if name in defined.get(rule, set()):
                    continue    # local convention: an unqualified citation
                    # inside a doc that DEFINES the rule means its own
                if QUALIFIED_RE.search(window):
                    continue          # qualified in the two-line window
                hits.append((name, i, rule))
    print(f"{len(ambiguous_rules)} rule numbers exist in >1 document")
    print(f"{len(hits)} unqualified ambiguous citations "
          f"(baseline {BASELINE})")
    for name, i, rule in hits[:15]:
        print(f"  {name}:{i}: Rule {rule} "
              f"(defined in {', '.join(sorted(defined[rule]))})")
    if len(hits) > 15:
        print(f"  ... and {len(hits) - 15} more")
    return 1 if len(hits) > BASELINE else 0


if __name__ == "__main__":
    sys.exit(main())
