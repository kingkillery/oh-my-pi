import json
try:
    s = json.load(open("/content/job_status.json"))
    b = s.get("base") if isinstance(s.get("base"), dict) else {}
    print("STATUS", s.get("status"), "stage=" + str(s.get("stage", "")), "base_agg=" + str(b.get("aggregate_accuracy")))
    if s.get("status") == "error":
        print("ERRTB", str(s.get("error")), str(s.get("tb", ""))[-500:])
except Exception as e:
    print("STATUS pending", repr(e))
