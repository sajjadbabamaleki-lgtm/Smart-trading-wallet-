#!/usr/bin/env bash
# M1/M2 acceptance run.
#
# One acceptance path, runnable in two places. This script holds every step of
# the M1/M2 verification; `.github/workflows/acceptance-m1-m2.yml` calls it
# rather than restating it, and `make accept` calls it locally. Two
# independently maintained acceptance paths would eventually disagree, and a
# project whose entire claim is evidence integrity cannot afford a verification
# that means different things depending on where it ran.
#
# It exists in runnable local form because GitHub Actions has rejected every job
# ever queued in this repository at zero billable milliseconds
# (docs/evidence/build-0.1/acceptance-attempts.md). Acceptance must not depend
# on infrastructure the project does not control.
#
# What it does, in order:
#
#   preflight -> provenance -> stack up -> migrate -> verify stores
#   -> integration tests -> assert execution guard -> live recording
#   -> replay verification -> container logs -> verdict
#
# Safety: this is a MARKET-DATA verification, not a trading verification. It
# holds no credential, submits no order, and asserts the execution guard before
# any network activity. Public Hyperliquid market data is read-only and mainnet
# execution stays hard-blocked by libs/config/settings.py (ADR-009).
#
# Evidence is written as each step completes, so a run that fails partway still
# leaves behind the evidence of how far it got — which is the more useful
# outcome of the two.

set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="$REPO_ROOT/infrastructure/docker/docker-compose.yml"

# 15 minutes rather than the 5 a metered CI run would default to. Five minutes
# of BTC data answers "do the frames parse"; it does not produce a latency
# distribution worth quoting. A local run is not billed by the minute, so the
# default buys the more useful answer. Use --minutes 120 or more for the
# capture that becomes the project's permanent fixture.
MINUTES="15"
MARKET_DATA_ENVIRONMENT="MAINNET_PUBLIC"
MINIMUM_FRAMES="50"
EVIDENCE_DIR="$REPO_ROOT/docs/evidence/build-0.1/live"
STOP_STACK="no"
HEALTH_TIMEOUT="240"

usage() {
    cat <<'USAGE'
Usage: accept_m1_m2.sh [options]

  --minutes N             Minutes to record from the live venue (default 15)
  --market-data ENV       MAINNET_PUBLIC (default) or TESTNET
  --minimum-frames N      Below this the live observation is INCONCLUSIVE (default 50)
  --out DIR               Evidence directory (default docs/evidence/build-0.1/live)
  --stop-stack            Stop the storage stack when finished (volumes are kept)
  --health-timeout N      Seconds to wait for stack health (default 240)
  -h, --help              This message

Market data is read-only. No credential is used and no order is ever submitted.

MAINNET_PUBLIC is the default because Hyperliquid's testnet book is thin and
unrepresentative, so testnet data cannot answer what the real venue sends.
Reading a public book risks nothing: the execution guard is asserted before
connecting and is never widened by this script.
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
        --minutes)        MINUTES="$2"; shift 2 ;;
        --market-data)    MARKET_DATA_ENVIRONMENT="$2"; shift 2 ;;
        --minimum-frames) MINIMUM_FRAMES="$2"; shift 2 ;;
        --out)            EVIDENCE_DIR="$2"; shift 2 ;;
        --stop-stack)     STOP_STACK="yes"; shift ;;
        --health-timeout) HEALTH_TIMEOUT="$2"; shift 2 ;;
        -h|--help)        usage; exit 0 ;;
        *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

case "$MARKET_DATA_ENVIRONMENT" in
    MAINNET_PUBLIC) VENUE_HOST="api.hyperliquid.xyz" ;;
    TESTNET)        VENUE_HOST="api.hyperliquid-testnet.xyz" ;;
    *) echo "--market-data must be MAINNET_PUBLIC or TESTNET, got '$MARKET_DATA_ENVIRONMENT'" >&2; exit 2 ;;
esac

cd "$REPO_ROOT"
mkdir -p "$EVIDENCE_DIR"

# ---------------------------------------------------------------------------
# Output helpers. Progress goes to stderr so that a caller redirecting stdout
# still gets a clean stream.
# ---------------------------------------------------------------------------

step()  { printf '\n\033[1m==> %s\033[0m\n' "$*" >&2; }
info()  { printf '    %s\n' "$*" >&2; }
warn()  { printf '\033[33m    warning: %s\033[0m\n' "$*" >&2; }
fail()  { printf '\033[31m    error: %s\033[0m\n' "$*" >&2; }

compose() { docker compose -f "$COMPOSE_FILE" "$@"; }

# ---------------------------------------------------------------------------
# Preflight
#
# The step CI does not need and a laptop does. Every check here is a failure
# mode that otherwise surfaces later disguised as something else: a busy port
# reads as a store that will not start, a blocked egress reads as a venue
# outage. Each one fails now, with the remedy named.
# ---------------------------------------------------------------------------

preflight() {
    step "Preflight"
    local problems=0

    command -v docker >/dev/null 2>&1 \
        || { fail "docker is not installed — https://docs.docker.com/get-docker/"; problems=$((problems + 1)); }

    if command -v docker >/dev/null 2>&1; then
        if docker info >/dev/null 2>&1; then
            info "docker daemon: running"
        else
            fail "the docker daemon is not running — start Docker Desktop, or 'sudo systemctl start docker'"
            problems=$((problems + 1))
        fi
        docker compose version >/dev/null 2>&1 \
            || { fail "docker compose v2 is unavailable ('docker compose version' failed)"; problems=$((problems + 1)); }
    fi

    command -v uv >/dev/null 2>&1 \
        || { fail "uv is not installed — https://docs.astral.sh/uv/"; problems=$((problems + 1)); }

    # Ports. Skipped when our own stack already holds them, which is the
    # ordinary case on a second run and not a conflict.
    local running=""
    if docker info >/dev/null 2>&1; then
        running="$(compose ps -q 2>/dev/null || true)"
    fi
    if [ -n "$running" ]; then
        info "stack already running; port check skipped"
    else
        local port
        for port in 5432 8123 9009 6379 9000 9001; do
            if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
                fail "port $port is already in use by another process — stop it, or the stack cannot bind"
                problems=$((problems + 1))
            fi
        done
        if [ "$problems" -eq 0 ]; then info "ports 5432 8123 9009 6379 9000 9001: free"; fi
    fi

    # Egress to the venue. Necessary, not sufficient: the recorder speaks
    # WebSocket and this probes HTTPS, so a pass does not guarantee the socket
    # opens — but a failure guarantees it will not, and that failure is worth
    # 10 seconds rather than 15 minutes.
    if command -v curl >/dev/null 2>&1; then
        # Assigned, then defaulted on failure. `$(curl ... || echo 000)` would
        # concatenate curl's own "000" with the fallback and report "000000".
        local code
        code="$(curl -sS -m 10 -o /dev/null -w '%{http_code}' \
            -X POST "https://$VENUE_HOST/info" \
            -H 'Content-Type: application/json' \
            -d '{"type":"meta"}' 2>/dev/null)" || code="000"
        if [ "$code" = "200" ]; then
            info "$VENUE_HOST: reachable"
        else
            if [ "$code" = "000" ]; then
                fail "$VENUE_HOST is unreachable — no HTTP response; the connection was blocked or refused"
            else
                fail "$VENUE_HOST returned HTTP $code — no usable route to the venue"
            fi
            info "a corporate proxy, VPN or egress filter is the usual cause; this repository's"
            info "sandbox sees HTTP 403 here, which is why this run belongs on your own machine"
            problems=$((problems + 1))
        fi
    else
        warn "curl not found; venue reachability not probed"
    fi

    # A stale .env silently changes what is verified. Settings forbids unknown
    # keys, so an outdated one fails startup much later, inside the safety
    # assertion, where it reads as a safety failure rather than a config file.
    if [ -f "$REPO_ROOT/.env" ]; then
        warn ".env exists — this run's explicit settings override it, but an unknown key in it still fails startup"
    fi

    if [ "$problems" -gt 0 ]; then
        fail "$problems preflight problem(s); nothing was started"
        exit 1
    fi
    info "preflight passed"
}

# ---------------------------------------------------------------------------
# Provenance. Recorded before anything can change it.
# ---------------------------------------------------------------------------

provenance() {
    step "Recording provenance"
    {
        echo "commit=$(git rev-parse HEAD 2>/dev/null || echo unknown)"
        echo "commit_dirty=$(git diff --quiet 2>/dev/null && echo false || echo true)"
        echo "branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
        echo "run_id=${GITHUB_RUN_ID:-local-$(date -u +%Y%m%dT%H%M%SZ)}"
        echo "runner=$(uname -srm)"
        echo "host_kind=$([ -n "${GITHUB_ACTIONS:-}" ] && echo github-actions || echo local)"
        echo "python=$(uv run python --version 2>&1 | tr -d '\n')"
        echo "uv=$(uv --version 2>&1 | tr -d '\n')"
        echo "docker=$(docker --version 2>&1 | tr -d '\n')"
        echo "compose=$(docker compose version 2>&1 | head -1 | tr -d '\n')"
        echo "lockfile_sha256=$(sha256sum uv.lock | cut -d' ' -f1)"
        echo "market_data_environment=$MARKET_DATA_ENVIRONMENT"
        echo "minutes=$MINUTES"
    } | tee "$EVIDENCE_DIR/provenance.txt"
}

# ---------------------------------------------------------------------------
# M1 — real storage stack
# ---------------------------------------------------------------------------

start_stack() {
    step "Starting the storage stack"
    compose up -d
    compose ps
}

wait_for_health() {
    step "Waiting for real readiness"
    # Waits on the compose healthchecks rather than sleeping: a fixed sleep
    # either wastes time or races, and a race here looks like a store failure.
    local deadline=$((SECONDS + HEALTH_TIMEOUT))
    local services="postgres clickhouse redis minio"
    while [ $SECONDS -lt $deadline ]; do
        local unhealthy=""
        local service cid status
        for service in $services; do
            cid="$(compose ps -q "$service" 2>/dev/null || true)"
            if [ -z "$cid" ]; then
                unhealthy="$unhealthy $service(absent)"
                continue
            fi
            status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid")"
            [ "$status" = "healthy" ] || unhealthy="$unhealthy $service($status)"
        done
        if [ -z "$unhealthy" ]; then
            info "all services healthy"
            return 0
        fi
        info "waiting on:$unhealthy"
        sleep 5
    done
    fail "services did not become healthy within ${HEALTH_TIMEOUT}s"
    compose ps
    return 1
}

wait_for_object_store() {
    step "Waiting for object store bootstrap"
    # minio-init creates and versions the bucket, then exits. Its exit code is
    # the evidence that the archive is ready.
    local deadline=$((SECONDS + 120))
    local cid state code
    while [ $SECONDS -lt $deadline ]; do
        cid="$(compose ps -aq minio-init 2>/dev/null || true)"
        if [ -n "$cid" ]; then
            state="$(docker inspect -f '{{.State.Status}}' "$cid")"
            if [ "$state" = "exited" ]; then
                code="$(docker inspect -f '{{.State.ExitCode}}' "$cid")"
                docker logs "$cid" 2>&1 | tail -20 >&2
                if [ "$code" = "0" ]; then info "bucket ready and versioned"; return 0; fi
                fail "minio-init exited $code"
                return 1
            fi
        fi
        sleep 3
    done
    fail "minio-init did not finish within 120s"
    return 1
}

record_service_versions() {
    step "Recording service versions"
    {
        echo "{"
        echo "  \"postgres\": \"$(compose exec -T postgres postgres --version | tr -d '\n')\","
        echo "  \"clickhouse\": \"$(compose exec -T clickhouse clickhouse-server --version | tr -d '\n')\","
        echo "  \"redis\": \"$(compose exec -T redis redis-server --version | tr -d '\n')\""
        echo "}"
    } | tee "$EVIDENCE_DIR/service-versions.json"
}

apply_migrations() {
    step "Applying migrations"
    uv run python infrastructure/scripts/verify_stack.py --migrate \
        | tee "$EVIDENCE_DIR/migrations.txt"
}

verify_stores() {
    step "Verifying every store"
    # --json is the machine-readable form the acceptance decision reads.
    uv run python infrastructure/scripts/verify_stack.py --json \
        > "$EVIDENCE_DIR/storage.json"
    cat "$EVIDENCE_DIR/storage.json" >&2
}

run_integration_tests() {
    step "Running integration tests"
    local code=0
    set +e
    uv run pytest tests/integration -m integration -v \
        --junitxml="$EVIDENCE_DIR/integration-junit.xml" \
        2>&1 | tee "$EVIDENCE_DIR/integration.txt"
    code="${PIPESTATUS[0]}"
    set -e
    # Written whatever the outcome, because the acceptance decision must be
    # able to distinguish failed from not-run.
    local passed="false"
    if [ "$code" = "0" ]; then passed="true"; fi
    printf '{"passed": %s, "exit_code": %s}\n' "$passed" "$code" \
        | tee "$EVIDENCE_DIR/integration.json"
    if [ "$code" != "0" ]; then warn "integration tests failed (exit $code); the acceptance decision will reflect it"; fi
}

# ---------------------------------------------------------------------------
# M2 — live public market data. Read-only.
# ---------------------------------------------------------------------------

# Store credentials, matching the compose file. Exported rather than passed so
# that every Python step below sees the same configuration.
export STW_MARKET_DATA_ENVIRONMENT="$MARKET_DATA_ENVIRONMENT"
export STW_EXECUTION_ENVIRONMENT="DEVELOPMENT"
export STW_TRADING_ENABLED="false"
export STW_ASSET_ALLOWLIST="BTC"
export STW_POSTGRES_DSN="postgresql://stw:stw@localhost:5432/stw"
export STW_CLICKHOUSE_URL="http://localhost:8123"
export STW_CLICKHOUSE_USER="stw"
export STW_CLICKHOUSE_PASSWORD="stw"
export STW_CLICKHOUSE_DATABASE="stw"
export STW_REDIS_URL="redis://localhost:6379/0"
export STW_OBJECT_STORE_ENDPOINT="http://localhost:9000"
export STW_OBJECT_STORE_BUCKET="stw-raw"
export STW_OBJECT_STORE_ACCESS_KEY="stw"
export STW_OBJECT_STORE_SECRET_KEY="stw-dev-only"

assert_execution_guard() {
    step "Asserting the execution guard before connecting"
    # Fails before any network activity if the configuration could reach
    # capital. Cheap, and the one check whose failure must stop everything.
    uv run python - <<'PY' | tee "$EVIDENCE_DIR/safety-assertion.txt"
import sys

from libs.config import load_settings

settings = load_settings()
checks = {
    "execution_cannot_reach_real_capital": not settings.execution_environment.reaches_real_capital,
    "order_submission_disabled": not settings.may_submit_orders,
    "no_credential_configured": not settings.testnet_api_wallet_private_key,
    "market_data_read_only": settings.market_data_is_read_only,
}
for name, ok in checks.items():
    print(f"{'PASS' if ok else 'FAIL'}  {name}")
print(f"market data endpoint: {settings.market_data_endpoint}")
print(f"execution endpoint:   {settings.venue_endpoint}")
if not all(checks.values()):
    print("refusing to proceed: this must be a read-only run", file=sys.stderr)
    sys.exit(1)
PY
}

live_verification() {
    step "Live acceptance verification (${MINUTES} minutes from $VENUE_HOST)"
    info "reading public market data only; no credential is loaded and no order can be sent"
    local code=0
    set +e
    uv run python infrastructure/scripts/acceptance_m1_m2.py \
        --minutes "$MINUTES" \
        --minimum-frames "$MINIMUM_FRAMES" \
        --out "$EVIDENCE_DIR" \
        --storage-report "$EVIDENCE_DIR/storage.json" \
        --integration-report "$EVIDENCE_DIR/integration.json" \
        --commit "$(git rev-parse HEAD 2>/dev/null || echo unknown)" \
        --run-id "${GITHUB_RUN_ID:-local-$(date -u +%Y%m%dT%H%M%SZ)}" \
        2>&1 | tee "$EVIDENCE_DIR/acceptance-stdout.txt"
    code="${PIPESTATUS[0]}"
    set -e
    return "$code"
}

replay_capture() {
    step "Replaying the captured live session"
    # Independent of the acceptance script's own determinism check, and over
    # the same capture — two paths agreeing is stronger evidence than one
    # asserting.
    if [ -s "$EVIDENCE_DIR/live-btc-capture.jsonl" ]; then
        set +e
        uv run python infrastructure/scripts/verify_replay.py \
            "$EVIDENCE_DIR/live-btc-capture.jsonl" \
            --out "$EVIDENCE_DIR" \
            2>&1 | tee "$EVIDENCE_DIR/replay-verification.txt"
        set -e
    else
        echo "no live capture was produced; replay not attempted" \
            | tee "$EVIDENCE_DIR/replay-verification.txt"
    fi
}

collect_logs() {
    step "Collecting container logs"
    mkdir -p "$EVIDENCE_DIR/container-logs"
    local service
    for service in postgres clickhouse redis minio minio-init; do
        compose logs --no-color "$service" \
            > "$EVIDENCE_DIR/container-logs/$service.log" 2>&1 || true
    done
    info "written to $EVIDENCE_DIR/container-logs/"
}

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

ACCEPTANCE_CODE=1

finish() {
    # Runs whatever happened, so a run that dies partway still leaves its logs
    # and still says where the evidence is.
    local exit_code=$?
    if docker info >/dev/null 2>&1 && [ -n "$(compose ps -q 2>/dev/null || true)" ]; then
        collect_logs
        if [ "$STOP_STACK" = "yes" ]; then
            step "Stopping the stack (volumes kept)"
            compose down || true
        else
            info "stack left running — 'make stack-down' stops it, volumes are kept either way"
        fi
    fi

    step "Evidence"
    info "$EVIDENCE_DIR"
    if [ -f "$EVIDENCE_DIR/m1-m2-acceptance.md" ]; then
        info "report: $EVIDENCE_DIR/m1-m2-acceptance.md"
    else
        warn "no acceptance report was produced; the run stopped before the decision"
    fi
    info ""
    info "Whatever the verdict, record it in docs/evidence/build-0.1/acceptance-attempts.md."
    info "An attempt that failed is evidence too, and it is the part that must not expire."
    exit "$exit_code"
}
trap finish EXIT

preflight
provenance
start_stack
wait_for_health
wait_for_object_store
record_service_versions
apply_migrations
verify_stores
run_integration_tests
assert_execution_guard
set +e
live_verification
ACCEPTANCE_CODE=$?
set -e
replay_capture

step "Verdict"
if [ "$ACCEPTANCE_CODE" != "0" ]; then
    fail "M1/M2 acceptance did not pass (verifier exit $ACCEPTANCE_CODE)"
    info "the evidence directory holds why; a NOT ACCEPTED result is a real result"
    exit "$ACCEPTANCE_CODE"
fi
printf '\033[32m    M1 and M2 ACCEPTED with live evidence.\033[0m\n' >&2
