import subprocess

for i in range(30):
    print("Running batch", i + 1)
    subprocess.run(["python", "oc_extract_taxonomy.py"])
