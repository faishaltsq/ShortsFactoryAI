# Pixel Studio — design contract (merged)

Console web untuk mengonfigurasi orchestrator tanpa menyentuh `.env`.
API: `apps/api` (FastAPI). UI: `apps/dashboard` (Next.js App Router + Tailwind).

## Menjalankan

```bash
uv run python scripts/run_studio_api.py                 # API loopback di http://127.0.0.1:8018
cd apps/dashboard && npm run dev                        # UI di http://127.0.0.1:3018
```

- `STUDIO_API_ORIGIN` defaults to `http://127.0.0.1:8018`; the Next.js server-side route handler proxies `/api/*` and keeps credentials out of browser code.
- `STUDIO_HOST` / `STUDIO_PORT` default to `127.0.0.1` / `8018`. The API launcher rejects non-loopback hosts.
- `STUDIO_TOKEN` is optional and, when set, protects every API route. The dashboard proxy adds it as a bearer token server-side; never put it in `config/studio.json` or git.

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
- **Prompt:** string kosong berarti memakai prompt bawaan `prompts.py`; `GET /api/studio` menyertakan `default_prompts` untuk editor.
- **Mode:** `mock` atau `live`; mode dan stop default diatur lewat Studio. Live calls use the configured HTTP providers and must not silently fall back to mock.

## Riwayat & rollback

Setiap simpan yang mengubah isi file menyalin versi lama ke `config/studio-history/studio-<UTC>Z.json` (maksimum 50 versi terbaru). File konfigurasi dan riwayat rollback bersifat lokal dan di-ignore oleh git.

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
