import json
count = 0
total = 0
with open('backend/data/judgments.jsonl') as f:
    for line in f:
        d = json.loads(line)
        total += 1
        if 'number amounting' in d['full_text'] or 'companyrt' in d['full_text']:
            count += 1
print(f"{count}/{total} judgments show this corruption pattern")