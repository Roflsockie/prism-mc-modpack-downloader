"""CurseForge Modpack Downloader - Flask Backend"""

import os
import json
import time
import zipfile
import shutil
import threading
import requests
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

BASE_DIR = Path(__file__).parent
DOWNLOAD_DIR = BASE_DIR / "download"
DOWNLOAD_DIR.mkdir(exist_ok=True)

API_CONFIG_FILE = BASE_DIR / "config.json"

def load_config():
    if API_CONFIG_FILE.exists():
        try:
            return json.loads(API_CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"api_key": ""}

def save_config(config):
    API_CONFIG_FILE.write_text(json.dumps(config, indent=4), encoding="utf-8")

config = load_config()

def get_api_key():
    return config.get("api_key", "")

def get_headers():
    return {"x-api-key": get_api_key(), "Accept": "application/json"}

API_BASE = "https://api.curseforge.com"
GAME_ID = 432
MODPACK_CLASS_ID = 4471


downloads = {}


def cdn_url(file_id, filename):
    fid = str(file_id)
    return f"https://edge.forgecdn.net/files/{fid[:-3]}/{fid[-3:]}/{filename}"


def classify_file(name):
    """Determine target folder for a mod file."""
    low = name.lower()
    if low.endswith(".jar"):
        return "mods"
    if not low.endswith(".zip"):
        return "mods"
    shader_kw = ["shader", "bsl", "complementary", "insanity", "sildurs",
                 "seus", "chocapic", "reimagined", "makeup", "spectrum"]
    for kw in shader_kw:
        if kw in low:
            return "shaderpacks"
    return "resourcepacks"


def api_get(path, params=None):
    r = requests.get(f"{API_BASE}{path}", headers=get_headers(), params=params, timeout=15)
    r.raise_for_status()
    return r.json()


def download_file(url, dest, dl_id, filename, retries=3):
    dl = downloads[dl_id]
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=60, stream=True)
            r.raise_for_status()
            total_size = int(r.headers.get('content-length', 0))

            start_time = time.time()
            downloaded = 0

            with open(dest, "wb") as f:
                for chunk in r.iter_content(8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        # Update byte progress and speed
                        elapsed = time.time() - start_time
                        if elapsed > 0:
                            speed = downloaded / elapsed # bytes per second
                            dl["speed"] = f"{speed / 1024 / 1024:.2f} MB/s"
                            if total_size > 0:
                                remaining = (total_size - downloaded) / speed if speed > 0 else 0
                                dl["eta"] = f"{int(remaining)}s"

                        dl["current_file"] = filename
                        dl["downloaded_bytes"] = dl.get("downloaded_bytes", 0) + len(chunk)

            return True
        except Exception as e:
            print(f"Error downloading {filename}: {e}")
            if attempt < retries - 1:
                time.sleep(1)
    return False


def do_download(dl_id, modpack_id, file_id, display_name):
    dl = downloads[dl_id]
    dl["status"] = "downloading"
    tmp_dir = BASE_DIR / "tmp" / dl_id
    tmp_dir.mkdir(parents=True, exist_ok=True)

    try:
        print(f"[{dl_id}] Starting download for {display_name}...")
        # 1) Get modpack file info
        dl["message"] = "Получение информации о модпаке..."
        dl["progress"] = 1
        file_info = api_get(f"/v1/mods/{modpack_id}/files/{file_id}")["data"]
        mp_filename = file_info["fileName"]
        mp_url = cdn_url(file_id, mp_filename)

        # 2) Download modpack zip
        dl["message"] = f"Скачивание структуры: {mp_filename}..."
        dl["progress"] = 2
        mp_zip = tmp_dir / mp_filename
        if not download_file(mp_url, mp_zip, dl_id, mp_filename):
            dl["status"] = "error"
            dl["message"] = "Ошибка скачивания файла структуры модпака"
            return

        # 3) Read manifest directly from zip (fast, no full extract)
        dl["message"] = "Чтение manifest.json..."
        with zipfile.ZipFile(mp_zip) as z:
            manifest_raw = z.read("manifest.json")
        if not manifest_raw:
            dl["status"] = "error"
            dl["message"] = "manifest.json не найден внутри архива"
            return
        manifest = json.loads(manifest_raw.decode("utf-8"))
        mod_files = manifest.get("files", [])
        total = len(mod_files)
        dl["total"] = total
        dl["eta"] = ""
        dl["speed"] = ""
        dl["message"] = f"Найдено {total} модов. Сборка структуры инстанса..."

        # 4) Create metadata files in memory (no disk for configs!)
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in display_name)
        override_folder = manifest.get("overrides", "overrides")
        override_prefix = override_folder + "/"
        mc_version = manifest.get("minecraft", {}).get("version", "1.20.1")
        mod_loaders = manifest.get("minecraft", {}).get("modLoaders", [])
        primary_loader = ""
        for ml in mod_loaders:
            if ml.get("primary"):
                primary_loader = ml["id"]
                break
        if not primary_loader and mod_loaders:
            primary_loader = mod_loaders[0]["id"]

        loader_uid = "net.minecraftforge"
        loader_ver = ""
        if primary_loader.startswith("forge-"):
            loader_uid = "net.minecraftforge"
            loader_ver = primary_loader.replace("forge-", "")
        elif primary_loader.startswith("neoforge-"):
            loader_uid = "net.neoforged"
            loader_ver = primary_loader.replace("neoforge-", "")
        elif primary_loader.startswith("fabric-"):
            loader_uid = "net.fabricmc.fabric-loader"
            loader_ver = primary_loader.replace("fabric-", "")
        elif primary_loader.startswith("quilt-"):
            loader_uid = "org.quiltmc.quilt-loader"
            loader_ver = primary_loader.replace("quilt-", "")

        # 5) Download all mods in parallel
        dl["message"] = f"Загрузка {total} модов..."
        dl["progress"] = 25
        mods_dir = tmp_dir / "mods"
        mods_dir.mkdir(exist_ok=True)
        failed = []

        def fetch_mod(mod_entry):
            pid, fid = mod_entry["projectID"], mod_entry["fileID"]
            try:
                info = api_get(f"/v1/mods/{pid}/files/{fid}")["data"]
                fn = info["fileName"]
                url = info.get("downloadUrl") or cdn_url(fid, fn)
                dest = mods_dir / fn
                if dest.exists() and dest.stat().st_size > 1000:
                    return True
                if download_file(url, dest, dl_id, fn) and dest.stat().st_size > 1000:
                    return True
                return False
            except Exception as e:
                print(f"[{dl_id}] Mod fetch error: {e}")
                return False

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(fetch_mod, m): m for m in mod_files}
            for future in as_completed(futures):
                dl["done"] = dl.get("done", 0) + 1
                dl["progress"] = 25 + int(dl["done"] / total * 65) if total > 0 else 25
                if not future.result():
                    failed.append(futures[future])

        # 6) Stream-build final zip (NO extracting configs to disk!)
        dl["message"] = "Сборка финального архива..."
        dl["progress"] = 90
        dl["eta"] = ""
        dl["speed"] = ""
        out_path = DOWNLOAD_DIR / f"{safe_name}.zip"

        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # 6a) Stream all files from structure zip with path remapping
            with zipfile.ZipFile(mp_zip, "r") as src:
                entries = [e for e in src.infolist() if not e.filename.endswith("/")]
                total_entries = len(entries)
                for idx, info in enumerate(entries):
                    name = info.filename
                    if name in ("manifest.json", "modlist.html"):
                        continue
                    if name.startswith(override_prefix):
                        arcname = f".minecraft/{name[len(override_prefix):]}"
                    else:
                        arcname = name
                    new_info = zipfile.ZipInfo(arcname, info.date_time)
                    new_info.compress_type = zipfile.ZIP_STORED
                    zf.writestr(new_info, src.read(name))
                    if idx % 5000 == 0:
                        dl["message"] = f"Конфиги: {idx}/{total_entries}"
                        dl["progress"] = 90 + int(idx / total_entries * 9)

            # 6b) Add mods (classify: mods/resourcepacks/shaderpacks)
            for f in sorted(mods_dir.iterdir()):
                if f.is_file():
                    folder = classify_file(f.name)
                    zf.write(f, f".minecraft/{folder}/{f.name}")

            # 6c) Add metadata
            mmc_data = json.dumps({
                "formatVersion": 1,
                "components": [
                    {"uid": "net.minecraft", "version": mc_version},
                    {"uid": loader_uid, "version": loader_ver}
                ]
            }, indent=4)
            zf.writestr("mmc-pack.json", mmc_data)
            zf.writestr("instance.cfg",
                f"[General]\nname={display_name}\nicon=\nnotes=\nlastLaunchTime=0\ntotalTimePlayed=0\n")

        dl["progress"] = 100
        dl["status"] = "done"
        dl["message"] = f"Готово! Скачано {total - len(failed)} из {total} модов"
        dl["filename"] = f"{safe_name}.zip"
        dl["failed"] = len(failed)
        dl["size_mb"] = round(out_path.stat().st_size / 1024 / 1024, 1)
        print(f"[{dl_id}] Finished: {out_path}")

    except Exception as e:
        print(f"[{dl_id}] Critical error: {e}")
        dl["status"] = "error"
        dl["message"] = f"Ошибка: {e}"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@app.route("/api/config", methods=["GET", "POST"])
def handle_config():
    if request.method == "GET":
        return jsonify(config)

    if request.method == "POST":
        body = request.json or {}
        new_key = body.get("api_key")
        if new_key:
            config["api_key"] = new_key
            save_config(config)
        return jsonify(config)

@app.route("/")
def index():
    return send_file(BASE_DIR / "index.html")


@app.route("/api/search")
def search():
    q = request.args.get("q", "").strip()
    page = max(0, int(request.args.get("page", 0)))
    if not q:
        return jsonify({"error": "пустой запрос"}), 400
    try:
        data = api_get("/v1/mods/search", {
            "gameId": GAME_ID, "classId": MODPACK_CLASS_ID,
            "searchFilter": q, "pageSize": 20, "index": page * 20,
            "sortField": 2, "sortOrder": "desc",
        })
        results = []
        for m in data.get("data", []):
            logo = ""
            for art in m.get("screenshots", []):
                logo = art.get("thumbnailUrl", "")
                break
            if not logo:
                logo = m.get("logo", {}).get("thumbnailUrl", "")
            results.append({
                "id": m["id"], "name": m["name"],
                "slug": m.get("slug", ""),
                "summary": (m.get("summary") or "")[:200],
                "downloads": m.get("downloadCount", 0),
                "logo": logo,
                "authors": ", ".join(a.get("name", "") for a in m.get("authors", [])),
            })
        return jsonify({"results": results, "total": data.get("pagination", {}).get("totalCount", 0)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/modpack/<int:modpack_id>/files")
def modpack_files(modpack_id):
    try:
        data = api_get(f"/v1/mods/{modpack_id}/files", {"pageSize": 50})
        files = []
        for f in data.get("data", []):
            files.append({
                "id": f["id"], "name": f["displayName"],
                "date": f.get("fileDate", ""),
                "size_mb": round(f.get("fileLength", 0) / 1024 / 1024, 1),
                "version": ", ".join(f.get("gameVersions", [])),
            })
        return jsonify({"files": files})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/download", methods=["POST"])
def start_download():
    body = request.json or {}
    modpack_id = body.get("modpack_id")
    file_id = body.get("file_id")
    display_name = body.get("display_name", "modpack")
    if not modpack_id or not file_id:
        return jsonify({"error": "нужны modpack_id и file_id"}), 400
    dl_id = f"{modpack_id}_{file_id}_{int(time.time())}"
    downloads[dl_id] = {
        "status": "starting",
        "message": "Подготовка...",
        "progress": 0,
        "done": 0,
        "total": 0,
        "current_file": "",
        "speed": "0 MB/s",
        "eta": "---",
        "downloaded_bytes": 0
    }
    threading.Thread(target=do_download, args=(dl_id, modpack_id, file_id, display_name), daemon=True).start()
    return jsonify({"download_id": dl_id})


@app.route("/api/progress/<dl_id>")
def progress(dl_id):
    dl = downloads.get(dl_id)
    if not dl:
        return jsonify({"error": "не найдено"}), 404
    return jsonify(dl)


@app.route("/api/file/<dl_id>")
def serve_file(dl_id):
    dl = downloads.get(dl_id)
    if not dl or dl["status"] != "done":
        return jsonify({"error": "нет файла"}), 404
    path = DOWNLOAD_DIR / dl["filename"]
    if not path.exists():
        return jsonify({"error": "файл не найден"}), 404
    return send_file(path, as_attachment=True)


if __name__ == "__main__":
    print(f"Сервер: http://localhost:5000")
    print(f"Загрузки: {DOWNLOAD_DIR}")
    app.run(host="0.0.0.0", port=5000, debug=False)
