# check_ids.py
import os
import pickle

# 1) pair_dir 에서 파일명 앞부분(ID) 뽑기
pair = "pair_dir"
pair_ids = sorted({
    fn.split("_", 1)[0]
    for fn in os.listdir(pair)
    if fn.lower().endswith(".png")
})
print("▶ pair_dir embedding IDs:", pair_ids)

# 2) package_dir 의 train.obj / val.obj 에 pickle 된 ID 뽑기
pkg = "package_dir"
for split in ("train", "val"):
    path = os.path.join(pkg, f"{split}.obj")
    ids = set()
    if os.path.exists(path):
        with open(path, "rb") as f:
            while True:
                try:
                    label, uni, img = pickle.load(f, encoding="latin1")
                    ids.add(label)
                except EOFError:
                    break
    print(f"▶ {split}.obj embedding IDs: {sorted(ids)}")
