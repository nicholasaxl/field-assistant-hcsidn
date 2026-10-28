# PRD: Field Assist

Final Project "Build for Hitachi", PT Hitachi Channel Solutions Indonesia. Disusun bersama Claude sebelum aplikasi dibangun, lalu diperbarui seiring pembuatan.

## 1. Masalah

Teknisi lapangan dan tim troubleshooting standby menangani gangguan ATM, POS, dan kiosk. Banyak gangguan sudah punya prosedur tertulis di manual, runbook, atau tabel kode error, tetapi dokumennya tersebar. Akibatnya orang tetap harus disiagakan untuk menjawab pertanyaan yang jawabannya sudah ada, dan sebagian gangguan (dugaan skimmer, pekerjaan kas dan brankas) tidak boleh ditangani sembarangan.

## 2. Tujuan

1. Menjawab gangguan yang terdokumentasi dalam hitungan detik, dari dokumen perusahaan sendiri.
2. Setiap langkah dapat dilacak ke dokumen sumbernya; langkah tanpa sumber ditandai.
3. Gangguan kritis dan topik berisiko selalu dieskalasi, diputuskan oleh aturan yang bisa diedit, bukan oleh model.
4. Mengurangi kebutuhan standby dan eskalasi untuk gangguan terdokumentasi. Bukan menggantikan teknisi.
5. Biaya nol per pertanyaan: model berjalan lokal; model online bersifat opsional.

## 3. Pengguna

| Pengguna | Kebutuhan |
|---|---|
| Teknisi lapangan ATM, POS, kiosk | Langkah yang benar dan cepat, dengan bukti sumber |
| Tim support level 2 | Ringkasan eskalasi yang lengkap (masalah, perangkat, langkah yang sudah dicoba) |
| Pengelola dokumen dan aturan | Menambah dokumen, mengubah aturan keselamatan, melihat celah pustaka |

## 4. Fitur inti (v1)

- Tanya jawab dari dokumen (PDF, DOCX, MD, TXT, CSV) dengan pencarian hybrid (vektor + kata kunci) dan pencarian kode error yang tepat.
- Jalur cepat: prosedur bernomor yang cocok disalin apa adanya, tanpa model.
- Sitasi yang dihitung, bukan dipercaya dari model.
- Penolakan untuk pertanyaan di luar dokumen, ditentukan oleh jarak pencarian.
- Aturan keselamatan (`data/policies.json`) dan eskalasi dengan ringkasan siap salin.
- "Fixed it / Didn't fix it", mode terpandu langkah demi langkah, pertanyaan klarifikasi, tindak lanjut singkat (3 giliran).
- Halaman Insights: pertanyaan per hari, tingkat berhasil, celah pustaka, langkah yang sering gagal, perkiraan waktu hemat (asumsi yang bisa diatur, ditandai sebagai perkiraan).
- Transparansi model: header dan setiap jawaban menyebut model dan lokasinya; opsi model online (Claude, OpenAI, Gemini, layanan kompatibel OpenAI) dengan API key, persetujuan eksplisit, dan kunci kebijakan.

## 5. Di luar lingkup v1

- Login, peran pengguna, multi-pengguna.
- OCR untuk PDF hasil scan.
- Integrasi sistem tiket (v1 menghasilkan ringkasan untuk disalin).
- Percakapan panjang bebas; memori sengaja dangkal (3 giliran).
- Upgrade model lokal (di luar anggaran proyek ini).

## 6. Ukuran keberhasilan

Diukur dengan `python -m src.evaluate --answers` pada `tests/eval_questions.json` (35 pertanyaan, 8 dokumen sintetis); hasil di `docs/scorecard.md`.

| Ukuran | Hasil terakhir (28 Okt 2026) |
|---|---|
| Jawaban lolos (dokumen benar, isi benar, tidak ditolak) | 95% |
| Pertanyaan di luar lingkup ditolak | 100% |
| Langkah terlacak ke sumber | 94% |
| Peringatan keselamatan muncul saat seharusnya | 100% |
| Waktu jawab median | 4,3 detik |

Di produksi: tingkat "Fixed it", jumlah jawaban yang mendapat respons, dan daftar celah pustaka di Insights.

## 7. Risiko dan batasan

- Jawaban dibatasi mutu model lokal kecil (qwen2.5:3b); jawaban yang ditulis model butuh 8 sampai 30 detik di CPU.
- Diuji pada dokumen sintetis. Uji sepuluh pertanyaan nyata (terutama bila dokumen berbahasa Indonesia) sebelum komitmen.
- Model pencarian cenderung condong ke bahasa Inggris.
- Satu pengguna, tanpa login.
- Penyedia model online baru diuji dengan klien tiruan; panggilan nyata pertama terjadi saat "Test connection" dengan key asli.

## 8. Usulan pilot

1. Muat manual, runbook, dan tiket nyata yang sudah selesai.
2. Jalankan 4 sampai 8 minggu paralel dengan standby (shadow mode).
3. Nilai dari Insights dan scorecard 50 sampai 100 pertanyaan nyata.
4. Kurangi standby hanya untuk kategori yang terbukti.
