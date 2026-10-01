# idxbot — bot saham IDX (monitoring + sinyal + paper trading + screener)

Desain sengaja **tidak mengirim order ke Stockbit**. Stockbit tidak punya API order resmi
(per pengecekan Okt 2026 — konfirmasi ke support Stockbit Sekuritas), dan mengotomasi
akun lewat endpoint tidak resmi berisiko melanggar ToS / akun diblokir.
Alurnya: bot hitung sinyal -> kirim rencana order -> **kamu pasang manual di Stockbit**.

## Setup
    pip install -r requirements.txt
    cp .env.example .env        # opsional, untuk Telegram & GOAPI
    # edit config.yaml (universe, strategi, fee, modal)

## Perintah
    python main.py backtest                      # data Yahoo (.JK), hasil di data/out/
    python main.py backtest --provider synthetic  # tes pipeline tanpa internet (data ACAK)
    python main.py daily                         # jalankan tiap hari SETELAH market tutup
    python main.py portfolio                     # lihat posisi paper
    python main.py reset                         # hapus DB paper
    python main.py screener                      # scan gabungan: TV + sinyal internal
    python main.py screener --provider synthetic  # tes screener tanpa internet
    python main.py tv                            # analisis TradingView murni (butuh internet)

Jadwal harian (cron, WIB, hari kerja):  `30 17 * * 1-5  cd /path/idxbot && python main.py daily`

## Alur `daily`
1. Isi order PENDING kemarin pakai harga open hari ini (paper, dengan slippage + batas limit)
2. Cek stop loss
3. Hitung sinyal dari close terakhir -> order baru (ukuran lot dari risk.py)
4. Kirim ringkasan ke konsol / Telegram

## Monitoring (mulai dari sini)
    python main.py monitor                 # loop; aktif hanya saat jam bursa (WIB)
    python main.py monitor --once          # satu siklus + tabel status (bisa kapan saja)
    python main.py monitor --once --digest # kirim ringkasan watchlist sekarang
    python main.py monitor --once --provider synthetic --force-open   # tes tanpa internet

Atur watchlist dan aturan di `config.yaml` bagian `monitor`.

### Aturan alert tersedia
| Tipe | Fungsi | Contoh value |
|------|--------|-------------|
| `price_above` / `price_below` | Harga melewati batas | `9000` |
| `pct_move` | Pergerakan harian >= N% | `4` |
| `volume_spike` | Volume >= Nx rata-rata 20 hari | `2.5` |
| `near_limit` | Dalam N% dari ARA/ARB | `1.0` |
| `gap_up` / `gap_down` | Gap >= N% | `3` |
| `consecutive_up` / `consecutive_down` | N hari berturut naik/turun | `5` |
| `rsi_oversold` / `rsi_overbought` | RSI menembus batas | `30` / `70` |
| `macd_cross_up` / `macd_cross_down` | MACD line cross signal | `1` |
| `bb_breakout` | Close di luar Bollinger Band | `1` |

Alert yang sama tidak diulang sebelum `cooldown_minutes`.
Setelah bursa tutup bot mengirim ringkasan harian (harga, % perubahan, volume, status strategi).

Jalankan terus-menerus di VPS/Raspberry Pi (contoh systemd, `~/.config/systemd/user/idxbot.service`):

    [Service]
    WorkingDirectory=/path/idxbot
    ExecStart=/path/idxbot/.venv/bin/python main.py monitor
    Restart=on-failure

## Screener
Perintah `screener` menggabungkan tiga sumber:

| Sumber | Data | Syarat |
|--------|------|--------|
| TradingView (via `tradingview_ta`) | RSI, MACD, ADX, rekomendasi | `pip install tradingview_ta` |
| IDX API (via GOAPI.IO) | Profil emiten, harga snapshot | API key (gratis, daftar di goapi.io) |
| Sinyal internal idxbot | SMA cross, breakout, RSI, MACD, Bollinger, combo | Data OHLCV |

Skor heuristik (bukan rekomendasi investasi!) menggabungkan semua sumber.

## Strategi tersedia
| Nama | Deskripsi | Parameter utama |
|------|-----------|-----------------|
| `sma_cross` | SMA fast/slow crossover | `fast`, `slow` |
| `breakout` | Donchian channel breakout | `entry`, `exit` |
| `rsi` | RSI mean-reversion | `period`, `oversold`, `overbought` |
| `macd_cross` | MACD line cross signal | `fast`, `slow`, `signal` |
| `bollinger` | Bollinger Band mean-reversion | `period`, `std_dev` |
| `combo` | RSI + MACD + SMA confluence | semua di atas |

Pilih di `config.yaml` bagian `strategy.name` dan `strategy.params`.

## Sumber data
| Provider | Kegunaan | Catatan |
|----------|----------|---------|
| `yfinance` | Data historis OHLCV (`.JK`) | Tidak resmi, kadang bolong |
| `csv` | Data lokal dari file CSV | Format: Date,Open,High,Low,Close,Volume |
| `synthetic` | Data acak (GBM) | Hanya untuk tes pipeline |
| `tradingview_ta` | Analisis teknikal real-time | MIT, `pip install tradingview_ta` |
| GOAPI.IO | Data resmi IDX (delay 3-10 menit) | Free tier, butuh API key |

## Tes
    python -m pytest tests/ -v

## Struktur
```
idxbot/
├── idxbot/
│   ├── sources/
│   │   ├── idx_api.py      # adapter GOAPI.IO / IDX public endpoint
│   │   └── tradingview.py   # wrapper tradingview_ta untuk screener
│   ├── screener.py          # scan gabungan: TV + IDX + sinyal internal
│   ├── monitor.py           # jadwal bursa, quote, 14 tipe aturan alert, dedupe
│   ├── idx_rules.py         # tick size, pembulatan harga, lot, ARA/ARB
│   ├── data.py              # yfinance / csv / synthetic, cache & pembersihan
│   ├── strategy.py          # 6 strategi: sma_cross, breakout, rsi, macd, bb, combo
│   ├── risk.py              # sizing posisi dan stop
│   ├── backtest.py          # backtest portofolio (sinyal di close t, exec di open t+1)
│   ├── paper.py             # paper broker (SQLite)
│   ├── runner.py            # siklus harian
│   └── notify.py            # Telegram
├── tests/
│   ├── test_monitor.py
│   ├── test_screener.py
│   └── test_enhancements.py
├── main.py
├── config.yaml
├── requirements.txt
├── .env.example
├── LICENSE                  # MIT
└── README.md
```

## Batasan yang perlu kamu tahu
- Angka fee, ARA/ARB, dan tick size adalah **default yang harus kamu verifikasi** (fee sheet Stockbit, aturan BEI).
- Data Yahoo untuk IDX kadang bolong/telat dan **tidak dikoreksi dividen**; cek sebelum percaya hasil.
- Data GOAPI delay 3-10 menit; untuk keputusan dengan uang asli, cek di aplikasi broker.
- Skor screener adalah **heuristik sederhana, bukan rekomendasi investasi**.
- Backtest belum memodelkan: likuiditas tipis, order tidak terisi, suspensi, corporate action, stop loss di hari entry.
- Setelah kena stop, sinyal yang masih aktif bisa memicu masuk lagi (whipsaw) — tambahkan cooldown kalau perlu.
- Backtest bagus bukan bukti strategi bekerja. Pantau paper trading minimal beberapa bulan sebelum uang asli.
- Data sintetis hanya untuk tes kode, bukan riset.
- Semua kode sumber data ditulis dari nol — tidak disalin dari repo MCP manapun.
