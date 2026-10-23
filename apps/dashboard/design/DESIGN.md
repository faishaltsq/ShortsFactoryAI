# Pixel Studio — design contract (merged)

Console web untuk mengonfigurasi orchestrator tanpa menyentuh `.env`.
API: `apps/api` (FastAPI). UI: `apps/dashboard` (Next.js App Router + Tailwind).

## Menjalankan

```bash
uv run python scripts/run_studio_api.py                 # API di http://127.0.0.1:8000/docs
cd apps/dashboard && npm run dev                        # UI di http://localhost:3000
```

- `STUDIO_API_ORIGIN` (default `http://127.0.0.1:8000`) dipakai Next.js `rewrites()` agar UI dan API terlihat satu origin — tidak ada CORS.
- `STUDIO_HOST` / `STUDIO_PORT` mengubah alamat API.
- `STUDIO_TOKEN` (opsional) melindungi semua route API. Isi nilainya hanya lewat environment; jangan pernah menaruhnya di `config/studio.json` atau di git.
- Bila `STUDIO_API_ORIGIN` di-set, header `X-Studio-Token` otomatis disisipkan oleh client Next.js.

## Halaman

| Halaman | Isi |
|---|---|
| Overview | Job hari ini, job berjalan, token & biaya vs budget, job terbaru, kesehatan provider |
| Studio | Model/temperature/prompt per agent, budget, parameter produksi, mode runner, riwayat konfigurasi + rollback |
| Jobs | Antrean produksi, filter state, pembuatan job baru |
| Job detail | Timeline stage, artifact JSON, log event, jalankan/batalkan run |
| Providers | Daftar provider + indikator sehat + tombol periksa ulang |
| Usage | Pemakaian token/biaya hari ini per agent |

## Konfigurasi

- **File:** `config/studio.json` (non-rahasia). Divalidasi Pydantic, ditulis atomik (`.tmp` lalu `replace`).
- **Precedence:** `studio.json` > environment > default bawaan.
- **Rahasia** (API key, kredensial) tetap di environment dan tidak pernah masuk file ini.
- **Override per agent** (`model`, `temperature`, `prompt`) diterapkan di `ProviderRouter.call()` sehingga berlaku untuk semua panggilan model berikutnya, tanpa restart. Router tetap menolak pemakaian strategist tanpa strategist.
- **Prompt:** string kosong berarti memakai prompt bawaan `prompts.py`. Tombol "Kembalikan default" mengosongkan override dan `GET /api/studio/prompts` mengembalikan teks bawaan untuk ditampilkan.
- **Mode:** `mock` (default, tanpa biaya) atau `live`. `live` tetap butuh health check model yang tervalidasi; kalau tidak, run masuk `BLOCKED`, bukan `FAILED`.

## Riwayat & rollback

Setiap simpan yang mengubah isi file menyalin versi lama ke `config/studio-history/studio-<UTC>Z.json` (maksimum 50 versi terbaru, di-commit ke git karena berisi prompt yang sudah dikurasi dan tidak berisi rahasia).

- `GET /api/studio/history` — daftar snapshot.
- `POST /api/studio/rollback {"name": "studio-...Z.json"}` — validasi snapshot, lalu jadikan konfigurasi aktif. Nama yang tidak valid atau snapshot rusak dibalas `409`.

## Menjalankan & membatalkan job

- `POST /api/jobs {"title": "...", "mode": "mock", "stop": "storyboard"}` → `202` + `job_id`; runner dijalankan di thread background dan tetap dikunci `JobStore.try_lock`.
- `POST /api/jobs/{id}/cancel` → flag in-memory dicek runner di batas stage, jadi run berhenti pada tahap berikutnya. State job tidak dipaksa ke `CANCELLED`; job tetap bisa dilanjutkan dengan "Jalankan / lanjutkan".
- UI polling (`2–2,5 s`) hanya berjalan selama ada run aktif dan berhenti otomatis saat selesai.

## File rusak

- Studio config rusak: CLI `scripts/run_pipeline.py` tetap berjalan memakai env/default dan mencetak warning; API menjawab `409` dengan alasan validasi — file rusak tidak pernah menimpa.
- `studio.json` yang valid tapi tanpa override sama sekali tidak mengubah perilaku pipeline apa pun.

## Batasan yang disengaja

- Run berjalan di thread, bukan worker terpisah. Kalau proses API mati di tengah run, state job tetap di SQLite dan lock expire setelah 30 menit.
- `RUNS` (status berjalan) di memori: hilang setelah restart API, bukan state job.
- Resolusi video, bahasa, dan seluruh rahasia tetap environment-only (butuh render ulang penuh, bukan angka form).

## Relationship to the illustrated pipeline

This shell is the operator console for the illustrated production pipeline.
The floor shows the twelve canonical roles (`packages/core/personas.py`); the
timeline, artifacts and approval gate come from the persisted state machine.
Approval is an operator action here, never automatic.
