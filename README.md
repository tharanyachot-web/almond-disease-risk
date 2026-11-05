# 🌰 Almond Disease Risk Predictor

A web tool that turns weather forecasts into a simple **Low / Medium / High** risk rating for two almond diseases, **Anthracnose** and **Bacterial Spot**, covering yesterday plus the next 7 days for any Australian postcode.

Built as an internship project to give growers early warning in terms they already use, instead of raw weather data.

## How it works

```
Postcode ──► Nominatim (geocode) ──► lat/lon
                                       │
                                       ▼
                         Flask API  /predict?lat=&lon=
                                       │
                     Open-Meteo hourly forecast (Melbourne time)
                                       │
          ┌────────────────────────────┼─────────────────────────────┐
          ▼                            ▼                             ▼
   Hourly wetness flag        Effective leaf temp           Max wind speed
   (rain, or RH ≥ 95 %        (+5 °C on clear,
    and T − Td ≤ 1 °C)         sunny hours)
          │                            │                             │
          ▼                            ▼                             ▼
   Wet streak, reset by       Daily mean leaf temp           Daily max wind
   a dry gap ≥ 4 h
          └──────────────┬─────────────┴─────────────────────────────┘
                         ▼
          Disease scores (0–7) ──► Low / Medium / High
```

Each disease is scored out of 7 on three factors:

| Factor | Anthracnose | Bacterial Spot |
|---|---|---|
| Wetness (longest wet run) | up to 3 pts (from 6 h) | up to 3 pts (from 21 h) |
| Leaf temperature | 3 pts at 10–25 °C | 3 pts at 25–30 °C |
| Wind ≥ 36 km/h | +1 | +1 |

**Score ≥ 6 → High · ≥ 4 → Medium · < 4 → Low**

Every threshold and the reasoning behind it is in **[docs/model-rules.md](docs/model-rules.md)**.

## Project structure

```
almond-disease-risk/
├── backend/
│   ├── app.py              # Flask API: weather fetch, wetness and leaf-temp model, risk scoring
│   └── requirements.txt
├── frontend/
│   └── index.html          # Single-page UI (Tailwind): postcode input and risk table
└── docs/
    └── model-rules.md      # Full rule set and scoring thresholds
```

## Running locally

**1. Start the backend**

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py                    # serves on http://127.0.0.1:5000
```

**2. Open the frontend**

Open `frontend/index.html` in your browser, enter a postcode (for example `3000` for Melbourne), and click **Get Disease Risk Forecast**.

The frontend reads its backend address from `API_BASE_URL` near the top of the `<script>` block in `index.html`. If you deploy the API somewhere else, point that constant to the deployed URL.

### API

`GET /predict?lat=<float>&lon=<float>` returns a JSON array with one object per day:

```json
{
  "date": "2025-11-05",
  "weather_code": 61,
  "avg_temperature_2m": 18.42,
  "avg_leaf_temp": 20.1,
  "avg_relative_humidity_2m": 78.5,
  "total_precipitation": 6.2,
  "max_wind_speed_10m": 24.3,
  "wet_hours": 9,
  "longest_wet_run": 14,
  "had_gap_break": true,
  "anthracnose_score": 5.0,
  "anthracnose_risk": "Medium",
  "bacterial_spot_score": 2.0,
  "bacterial_spot_risk": "Low"
}
```

## Data sources

- **Weather:** [Open-Meteo Forecast API](https://open-meteo.com/) (free, no API key needed)
- **Geocoding:** [OpenStreetMap Nominatim](https://nominatim.openstreetmap.org/)

## Limitations

- Leaf temperature uses a fixed +5 °C sunshine boost, not a full energy-balance model.
- Leaf wetness is estimated from weather variables, not measured by a sensor.
- Risk ratings are decision-support guidance only and don't replace in-orchard monitoring or advice from an agronomist.

## Tech stack

Python · Flask · pandas · NumPy · Open-Meteo SDK · HTML · Tailwind CSS · vanilla JavaScript
