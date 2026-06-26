#!/usr/bin/env bash
# Orchestrate the full verifier distillation on a Colab T4: provision -> install -> launch
# (detached on the kernel) -> poll job_status.json -> fetch result+adapter -> stop.
cd /mnt/c/dev/Desktop-Projects/pi-llm-as-verifier || exit 1
S=vd

echo "[1] provision T4"
colab new -s "$S" --gpu T4 2>&1 | grep -aiE 'ready|error|400|unassign'
echo "[2] GPU check"
echo 'import torch;print("GPUCHK", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "NONE")' | colab exec -s "$S" 2>&1 | grep -a GPUCHK
echo "[3] install deps"
colab install -s "$S" transformers peft trl bitsandbytes datasets accelerate 2>&1 | grep -aiE 'complete|error'
echo "[4] launch (detached)"
colab exec -s "$S" -f distill/colab_job.py 2>&1 | grep -aE 'LAUNCHED|Error|Traceback'

echo "[5] poll (up to ~60 min)"
for i in $(seq 1 48); do
  sleep 75
  st=$(colab exec -s "$S" -f distill/_poll.py 2>/dev/null | grep -a STATUS)
  echo "[poll $i] $st"
  echo "$st" | grep -qaE ' done | error ' && break
  echo "$st" | grep -qaE 'STATUS (done|error)' && break
done

echo "[6] result"
echo 'import os
print("RES " + open("/content/eval_result.json").read()) if os.path.exists("/content/eval_result.json") else print("RES NO_RESULT")' | colab exec -s "$S" 2>&1 | grep -aE 'RES|aggregate|raw_call|flip|base|tuned|model'
echo "[7] zip + download"
echo 'import shutil,os
print("ZIP", shutil.make_archive("/content/distill_adapter","zip","/content/distill_adapter")) if os.path.isdir("/content/distill_adapter") else print("NOADAPTER")' | colab exec -s "$S" 2>&1 | grep -aiE 'ZIP|NOADAPTER'
colab download -s "$S" /content/distill_adapter.zip ./distill/adapter.zip 2>&1 | tail -2
colab download -s "$S" /content/eval_result.json ./distill/eval_result.json 2>&1 | tail -2
echo "[8] log tail"
colab log -s "$S" -n 8 2>&1 | grep -aiE 'error|done|keep' | tail -6
echo "[9] stop"
colab stop -s "$S" 2>&1 | tail -2
echo "DONE_RUN_FULL"
