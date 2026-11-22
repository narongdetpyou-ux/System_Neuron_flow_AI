#!/usr/bin/env bash
# Examine one model on every exam set (own-model track T4, training/exam.py), as the Own model exam workflow does.
#
#   .github/scripts/run_exam.sh <label> <model file> <model id> [limit]
#
# 1. starts llama.cpp's server (~/llama-bin/llama-server) with the recipe's serving flags, which a test ties to the
#    local lane's: thinking off, temperature 0, repeat penalty 1.05, seed 42, context 16384;
# 2. runs the probe: 8 clear development cases must come back well formed with the right category, or it stops;
# 3. runs every exam set of training.exam.EXAM_SETS with the local provider into reports/<label>/<label>-<set>.json;
# 4. prints the EXAM-CASE and EXAM-METRICS lines (ids and labels, never case text) and stops the server.
set -euo pipefail
label="$1"
model_path="$2"
model_id="$3"
limit="${4:-}"
mkdir -p "reports/$label" "reports/probe-$label"
read -r -a flags <<< "$(python -c "from training.receipt import load_recipe
s = load_recipe()['serving']
print(f\"--reasoning {s['reasoning']} --temp {s['temperature']} --repeat-penalty {s['repeat_penalty']} \"
      f\"--seed {s['seed']} --ctx-size {s['ctx_size']}\")")"
log="${RUNNER_TEMP:-/tmp}/llama-server-$label.log"
~/llama-bin/llama-server -m "$model_path" --alias "$model_id" --host 127.0.0.1 --port 8080 --parallel 2 \
  "${flags[@]}" --no-webui --no-slots > "$log" 2>&1 &
pid=$!
trap 'kill "$pid" 2> /dev/null || true' EXIT
for _ in $(seq 1 150); do
  if curl -fsS http://127.0.0.1:8080/health > /dev/null 2>&1; then break; fi
  if ! kill -0 "$pid" 2> /dev/null; then break; fi
  sleep 2
done
if ! curl -fsS http://127.0.0.1:8080/health > /dev/null 2>&1; then
  echo "::error::the model server did not start for $label"
  tail -n 40 "$log"
  exit 1
fi
export NEURON_FLOW_LLM_MODEL="$model_id"
args=()
if [ -n "$limit" ]; then args+=(--limit "$limit"); fi
python -m training.exam make-probe --out "reports/probe-$label/cases.json"
python -m app.eval.triage_shadow_eval --golden "reports/probe-$label/cases.json" \
  --out "reports/probe-$label/report.json" > /dev/null
if ! python -m training.exam probe-check "reports/probe-$label/report.json"; then
  echo "::error::$label failed the probe: its answers are malformed or wrong on clear cases; the exam stopped"
  exit 1
fi
while IFS=: read -r name golden; do
  python -m app.eval.triage_shadow_eval --golden "$golden" --out "reports/$label/$label-$name.json" "${args[@]}" \
    > /dev/null
done < <(python -c "from training.exam import EXAM_SETS
print('\n'.join(f'{name}:{path}' for name, path in EXAM_SETS))")
python -m training.exam digest --label "$label" reports/"$label"/"$label"-*.json
