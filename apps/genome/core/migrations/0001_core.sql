-- genome core schema (BUILD.md Phase 0.2). One schema, realm as a column:
-- genome-spec.md Rule 3.5 — realms are logical, isolation is query discipline.
CREATE SCHEMA IF NOT EXISTS genome;

CREATE TABLE IF NOT EXISTS genome.world (
    realm_id      uuid PRIMARY KEY,
    owner_user_id text,                          -- NULL = tombstoned (Rule 3.6) or commons
    kinds         smallint[2] NOT NULL,          -- two of the 20 (Rule 2.2)
    colours       text[2]     NOT NULL,          -- A100 hex pair (Rule 4.9)
    founding_centre jsonb     NOT NULL,          -- recorded per genotype-spec Rule 3.2b
    flood_at      timestamptz,                   -- undisclosed to agents (construction 4.7)
    countdown_visible_at timestamptz,            -- flood fires 2d after THIS (calibration 3.0f)
    is_commons    boolean NOT NULL DEFAULT false,
    commons_shard uuid,                          -- stable assignment (Rule 6.2h)
    aggregate_stock jsonb NOT NULL DEFAULT '{}', -- per-kind, vs 250 ceiling (Rule 4.13)
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS genome.agent (
    agent_uuid    uuid PRIMARY KEY,
    realm_id      uuid NOT NULL REFERENCES genome.world(realm_id),  -- where it IS
    home_realm    uuid NOT NULL REFERENCES genome.world(realm_id),  -- birth world
    owner_user_id text NOT NULL,
    name          text NOT NULL,                 -- three words (Rule 7.13)
    parents       uuid[],                        -- NULL for founders
    genotype      jsonb NOT NULL,
    colour_pair   text[2] NOT NULL,
    models        jsonb NOT NULL,                -- per-tier assignment (exec 10.1)
    cargo         jsonb NOT NULL DEFAULT '{}',   -- per-kind fractions, Σ ≤ 15
    stamina       real NOT NULL, stamina_max real NOT NULL,
    mana          real NOT NULL, mana_max    real NOT NULL,
    victories     int  NOT NULL DEFAULT 0,       -- Attrition input (Rule 3.8c)
    born_at       timestamptz NOT NULL DEFAULT now(),
    alive         boolean NOT NULL DEFAULT true,
    cert_ref      text
);
CREATE INDEX IF NOT EXISTS agent_by_realm ON genome.agent(realm_id) WHERE alive;

CREATE TABLE IF NOT EXISTS genome.movement (
    agent_uuid  uuid PRIMARY KEY REFERENCES genome.agent(agent_uuid),
    realm_id    uuid NOT NULL,
    from_x real NOT NULL, from_y real NOT NULL,
    to_x   real NOT NULL, to_y   real NOT NULL,
    departed_at timestamptz NOT NULL,
    arrives_at  timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS genome.pile (
    pile_uuid   uuid PRIMARY KEY,
    realm_id    uuid NOT NULL REFERENCES genome.world(realm_id),
    kind        smallint NOT NULL,
    x real NOT NULL, y real NOT NULL,
    qty_at      real NOT NULL,
    measured_at timestamptz NOT NULL,
    rate        real NOT NULL,                   -- own random rate (Rule 4.6)
    cap         real NOT NULL
);
CREATE INDEX IF NOT EXISTS pile_by_realm ON genome.pile(realm_id);

-- The queue's source of truth (system-spec Rule 8.3): Redis schedules, this table IS.
CREATE TABLE IF NOT EXISTS genome.event (
    event_id    bigserial PRIMARY KEY,
    realm_id    uuid NOT NULL,
    due_at      timestamptz NOT NULL,
    kind        text NOT NULL,
    subject_uuid uuid,
    payload     jsonb NOT NULL DEFAULT '{}',
    done_at     timestamptz
);
CREATE INDEX IF NOT EXISTS event_due ON genome.event(realm_id, due_at) WHERE done_at IS NULL;

CREATE TABLE IF NOT EXISTS genome.opinion (
    observer_uuid uuid NOT NULL,
    subject_uuid  uuid NOT NULL,   -- observer's own uuid = the general opinion (6.9a)
    attribute     text NOT NULL,
    estimate      real NOT NULL,
    weight        real NOT NULL,
    updated_at    timestamptz NOT NULL DEFAULT now(),
    owner_sourced boolean NOT NULL DEFAULT false,  -- Rule 13.5a mark
    relay_depth   int NOT NULL DEFAULT 0,          -- Rule 6.10b compounding
    PRIMARY KEY (observer_uuid, subject_uuid, attribute)
);

-- The experimental record (execution-spec §6): append-only, never sampled.
CREATE TABLE IF NOT EXISTS genome.decision (
    decision_id bigserial PRIMARY KEY,
    agent_uuid  uuid NOT NULL,
    at          timestamptz NOT NULL DEFAULT now(),
    situation   text NOT NULL,
    inputs      jsonb NOT NULL,
    model       text NOT NULL,
    tier        text NOT NULL,
    choice      jsonb NOT NULL
);

CREATE TABLE IF NOT EXISTS genome.model_key (
    user_id   text NOT NULL,
    scope     text NOT NULL CHECK (scope IN ('world','owned')),
    provider  text NOT NULL,
    ciphertext bytea NOT NULL,                   -- never in a decision record (exec 9.3)
    visitors_allowed boolean NOT NULL DEFAULT false,
    PRIMARY KEY (user_id, scope, provider)
);

CREATE TABLE IF NOT EXISTS genome.connection (
    user_a text NOT NULL, user_b text NOT NULL,
    confirmed_at timestamptz NOT NULL,           -- mutual only (system-spec 9.4)
    PRIMARY KEY (user_a, user_b), CHECK (user_a < user_b)
);
