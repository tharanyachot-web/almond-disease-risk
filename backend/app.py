"""Flask API that translates Open-Meteo forecasts into easy almond disease risk guidance."""

import pandas as pd
import openmeteo_requests
import numpy as np
from flask import Flask, request, jsonify
from flask_cors import CORS

# --- Server Initialisation ---
app = Flask(__name__)
CORS(app)

def print_daily_summary(daily_summary, lat, lon):
    """Print a friendly table of the forecast and risk ratings so the team can sanity-check each run 
    without digging into JSON."""

    # Resetting the index to make 'date' a column for printing
    df_print = daily_summary.reset_index()

    # Formatting columns for clear terminal output
    df_print['Air 2m (°C)'] = df_print['avg_temperature_2m'].round(1)
    df_print['Leaf (°C)'] = df_print['avg_effective_temp'].round(1)
    df_print['Total Rain (mm)'] = df_print['total_precipitation'].round(1)
    df_print['Wet Hours'] = df_print['wet_hours'].astype(int)

    # Selecting the final columns for display
    print_cols = ['date', 'Air 2m (°C)', 'Leaf (°C)', 'Total Rain (mm)', 'Wet Hours', 'anthracnose_risk', 'bacterial_spot_risk']

    print("-" * 80)
    print(f"REQUEST PROCESSED FOR: Lat={lat:.4f}, Lon={lon:.4f}")
    print("7-Day Disease Risk Forecast (Leaf Temp = Effective Temp):")
    print("-" * 80)
    print(df_print[print_cols].to_string(index=False))
    print("-" * 80)


def get_effective_leaf_temp(hourly_temp, cloud_cover, solar_radiation):
    """Add a simple sunshine bonus to the air temperature so the model reflects 
    how sunlight can heat the leaves above the air."""
    # Thresholds for 'Sunny' conditions:
    MAX_CLOUD_FOR_SUN = 20.0  # Max cloud cover (in percent) considered clear enough for a temperature boost.
    TEMP_BOOST = 5          # The simplified temperature increase (°C) based on the 5-10C research finding.
    MIN_SOLAR_FOR_BOOST = 100.0 # Minimum solar radiation (W/m²) required to confirm daytime/sun effect.

    # Apply the boost only if clear sky AND daytime (solar radiation is present).
    apply_boost = (cloud_cover <= MAX_CLOUD_FOR_SUN) & (solar_radiation > MIN_SOLAR_FOR_BOOST)
    boost_array = np.where(apply_boost, TEMP_BOOST, 0.0)

    return hourly_temp + boost_array

def get_weather_forecast(latitude, longitude):
    """Request the next week of hourly weather from Open-Meteo, 
    returning a DataFrame we can enrich with leaf temperature."""
    try:
        openmeteo = openmeteo_requests.Client()

        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": [
                "temperature_2m",
                "dewpoint_2m",
                "cloud_cover",
                "precipitation",
                "relative_humidity_2m",
                "wind_speed_10m",
                "shortwave_radiation"
            ],
            "timezone": "Australia/Melbourne",
            "past_days": 1,
        }

        responses = openmeteo.weather_api(url, params=params)
        response = responses[0]

        hourly = response.Hourly()
        hourly_variables = list(map(lambda i: hourly.Variables(i), range(0, hourly.VariablesLength())))

        # NOTE: The order of variables MUST match the request above.
        hourly_data = {
            "date": pd.date_range(
                start=pd.to_datetime(hourly.Time(), unit="s"),
                end=pd.to_datetime(hourly.TimeEnd(), unit="s"),
                freq=pd.Timedelta(seconds=hourly.Interval()),
                inclusive="left"
            ),
            "temperature_2m": hourly_variables[0].ValuesAsNumpy(),
            "dewpoint_2m": hourly_variables[1].ValuesAsNumpy(),
            "cloud_cover": hourly_variables[2].ValuesAsNumpy(),
            "precipitation": hourly_variables[3].ValuesAsNumpy(),
            "relative_humidity_2m": hourly_variables[4].ValuesAsNumpy(),
            "wind_speed_10m": hourly_variables[5].ValuesAsNumpy(),
            "shortwave_radiation": hourly_variables[6].ValuesAsNumpy()
        }

        df = pd.DataFrame(data=hourly_data)

        # 1. Calculate Effective Leaf Temperature
        df['effective_temp'] = get_effective_leaf_temp(df['temperature_2m'], df['cloud_cover'], df['shortwave_radiation'])

        return df

    except Exception as e:
        print(f"Error fetching weather data: {e}")
        return None


def get_daily_weather_code(latitude, longitude):
    """Fetch the daily weather codes so the front end can attach simple words or icons that growers recognise."""
    try:
        openmeteo = openmeteo_requests.Client()

        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "daily": ["weathercode"],
            "timezone": "Australia/Melbourne",
            "past_days": 1,
        }

        responses = openmeteo.weather_api(url, params=params)
        response = responses[0]

        daily = response.Daily()
        if daily is None or daily.VariablesLength() == 0:
            return None

        dates = pd.date_range(
            start=pd.to_datetime(daily.Time(), unit="s"),
            end=pd.to_datetime(daily.TimeEnd(), unit="s"),
            freq=pd.Timedelta(seconds=daily.Interval()),
            inclusive="left"
        )
        dates = dates.tz_localize('UTC').tz_convert('Australia/Melbourne') if dates.tz is None else dates
        codes = daily.Variables(0).ValuesAsNumpy().astype(int)

        return pd.DataFrame({
            "date": dates.tz_localize(None).normalize() if dates.tz is not None else dates.normalize(),
            "weather_code": codes
        })

    except Exception as e:
        print(f"Error fetching daily weather codes: {e}")
        return None

def continuous_wet_with_gap_reset(is_wet: pd.Series, max_dry_gap: int = 4) -> pd.Series:
    """Track how many consecutive hours leaves stayed wet, forgiving short dry breaks up to 
    the allowed gap (4 hrs) so brief pauses do not reset the streak."""
    cont = np.zeros(len(is_wet), dtype=int)
    wet_streak = 0
    dry_gap_hours = 0

    for i, wet in enumerate(is_wet.astype(bool)):
        if wet:
            if dry_gap_hours >= max_dry_gap:
                wet_streak = 0  # reset if we exceeded the tolerated dry gap
            dry_gap_hours = 0
            wet_streak += 1
        else:
            dry_gap_hours += 1
            if dry_gap_hours >= max_dry_gap:
                wet_streak = 0
        cont[i] = wet_streak

    return pd.Series(cont, index=is_wet.index)


def day_has_gap_break(is_wet: pd.Series, max_dry_gap: int = 4) -> bool:
    """Return True when the day experienced a dry spell long enough (≥ max_dry_gap hours) 
    to fully reset the wet streak counter."""
    dry_run = 0
    for wet in is_wet.astype(bool):
        if wet:
            dry_run = 0
        else:
            dry_run += 1
            if dry_run >= max_dry_gap:
                return True
    return False


def get_effective_continuous_wet_hours(daily_data) -> int:
    """Return the longest block of back-to-back wet hours the leaves experienced during the day, 
    including runs that continued past midnight."""
    longest_run = daily_data.get('longest_wet_run', np.nan)
    if pd.isna(longest_run):
        longest_run = 0
    continuous_at_eod = daily_data.get('continuous_wet_at_eod', np.nan)
    if pd.isna(continuous_at_eod):
        continuous_at_eod = 0
    return int(max(longest_run, continuous_at_eod))


def predict_anthracnose_risk_score(daily_data):
    """Combine wet hours, leaf warmth, and wind to judge how friendly the day was for Anthracnose infection, 
    returning a simple 7 scaling score."""
    continuous_wet = get_effective_continuous_wet_hours(daily_data)
    if continuous_wet == 0:
        return 0.0

    score = 0.0

    # 1. Wetness Score (out of 3) - Priority Factor
    if continuous_wet >= 23:
        score += 3
    elif continuous_wet >= 12:
        score += 2
    elif continuous_wet >= 6:
        score += 1

    # 2. Temperature Score (out of 3) - Using Effective Leaf Temp
    # Align with UI by rounding the effective temperature before threshold checks
    avg_temp = round(daily_data['avg_effective_temp'], 1)
    if 10 <= avg_temp <= 25:
        score += 3
    elif 5 <= avg_temp < 10 or 25 < avg_temp <= 30:
        score += 1

    # 3. Wind Speed Score (out of 1) - Spread Factor
    max_wind_kmh = daily_data['max_wind_speed_10m']
    # Rogers and Kimpton (2011) note spore liberation when wind ≥ 10 m/s (~36 km/h), so we apply 36 km/h threshold.
    if max_wind_kmh >= 36:
        score += 1

    return round(score, 2)

def predict_bacterial_spot_risk_score(daily_data):
    """Score Bacterial Spot risk using the same weather story, but requiring much longer wet streaks 
    to trigger risk because this disease is harder to start."""
    continuous_wet = get_effective_continuous_wet_hours(daily_data)
    if continuous_wet == 0:
        return 0.0

    score = 0.0

    # 1. Wetness Score (out of 3) - Priority Factor
    if continuous_wet >= 23:
        score += 3
    elif continuous_wet >= 22:
        score += 2
    elif continuous_wet >= 21:
        score += 1

    # 2. Temperature Score (out of 3) - Using Effective Leaf Temp
    avg_temp = round(daily_data['avg_effective_temp'], 1)
    if 25 <= avg_temp <= 30:
        score += 3
    elif 10 <= avg_temp < 25 or 30 < avg_temp <= 35:
        score += 2
    elif avg_temp >= 5:
        score += 1

    # 3. Wind Speed Score (out of 1) - Spread Factor
    max_wind_kmh = daily_data['max_wind_speed_10m']
    if max_wind_kmh >= 36:
        score += 1

    return round(score, 2)

def map_score_to_risk(score):
    """Translate the numeric score into the Low, Medium, or High label growers see on the dashboard."""
    if score >= 6:
        return 'High'
    elif score >= 4:
        return 'Medium'
    else:
        return 'Low'

# --- API Endpoint ---
@app.route('/predict')
def predict_risk():
    lat = request.args.get('lat', type=float)
    lon = request.args.get('lon', type=float)

    if lat is None or lon is None:
        return jsonify({"error": "Latitude and Longitude parameters are required"}), 400

    hourly_data = get_weather_forecast(lat, lon)
    daily_weather_codes = get_daily_weather_code(lat, lon)

    if hourly_data is None:
        return jsonify({"error": "Could not fetch weather data."}), 500

    # Hour flagged wet if raining OR if humidity ≥95% while air-dewpoint spread ≤1°C.
    hourly_data['is_wet'] = (hourly_data['precipitation'] > 0) | (
        (hourly_data['relative_humidity_2m'] >= 95) &
        ((hourly_data['temperature_2m'] - hourly_data['dewpoint_2m']) <= 1.0)
)
    hourly_data['is_wet'] = hourly_data['is_wet'].astype(bool)
    hourly_data['day'] = hourly_data['date'].dt.floor('D')

    # Continuity tolerates up to 4 consecutive dry hours before resetting to zero.
    # Compute across the entire timeline so streaks can span multiple days.
    hourly_data['continuous_wet'] = continuous_wet_with_gap_reset(
        hourly_data['is_wet'], max_dry_gap=4
    )

    gap_break_by_day = hourly_data.groupby('day').apply(
        lambda group: day_has_gap_break(group['is_wet'], max_dry_gap=4)
    )

    # Resamples the hourly data into a daily summary.
    daily_summary = hourly_data.resample('D', on='date').agg(
        avg_temperature_2m=('temperature_2m', 'mean'),
        avg_effective_temp=('effective_temp', 'mean'),
        total_precipitation=('precipitation', 'sum'),
        max_wind_speed_10m=('wind_speed_10m', 'max'),
        avg_relative_humidity_2m=('relative_humidity_2m', 'mean'),
        wet_hours=('is_wet', 'sum'),
        longest_wet_run=('continuous_wet', 'max'),
        continuous_wet_at_eod=('continuous_wet', 'last')
    )
    daily_summary['had_gap_break'] = daily_summary.index.map(gap_break_by_day)
    zero_wet_mask = daily_summary['wet_hours'] == 0
    if zero_wet_mask.any():
        # Fully dry days should not inherit a previous day's wet streak in the summary metrics.
        daily_summary.loc[zero_wet_mask, ['longest_wet_run', 'continuous_wet_at_eod']] = 0

    if daily_weather_codes is not None and not daily_weather_codes.empty:
        code_map = daily_weather_codes.set_index('date')['weather_code']
        normalized_index = daily_summary.index.tz_localize(None) if daily_summary.index.tz is not None else daily_summary.index
        normalized_index = normalized_index.normalize()
        mapped_codes = pd.Series(normalized_index, index=daily_summary.index).map(code_map)
        daily_summary['weather_code'] = mapped_codes
    else:
        daily_summary['weather_code'] = None

    # Drop days earlier than "yesterday" in Melbourne so we only keep one historical day.
    mel_yesterday = (pd.Timestamp.now(tz='Australia/Melbourne') - pd.Timedelta(days=1)).normalize()
    if daily_summary.index.tz is None:
        min_allowed = mel_yesterday.tz_localize(None)
    else:
        min_allowed = mel_yesterday.tz_convert(daily_summary.index.tz)
    daily_summary = daily_summary[daily_summary.index >= min_allowed]

    daily_summary['anthracnose_score'] = daily_summary.apply(predict_anthracnose_risk_score, axis=1)
    daily_summary['bacterial_spot_score'] = daily_summary.apply(predict_bacterial_spot_risk_score, axis=1)
    daily_summary['anthracnose_risk'] = daily_summary['anthracnose_score'].apply(map_score_to_risk)
    daily_summary['bacterial_spot_risk'] = daily_summary['bacterial_spot_score'].apply(map_score_to_risk)

    # --- Debug/Monitoring Output ---
    # This prints the results to the terminal where the server is running.
    print_daily_summary(daily_summary, lat, lon)

    # Converts the final results into a JSON format suitable for the web page.
    results = daily_summary.reset_index().to_dict('records')

    # Formats the data for a clean display on the web page.
    for result in results:
        result['date'] = result['date'].strftime('%Y-%m-%d')
        result['avg_temperature_2m'] = round(result['avg_temperature_2m'], 2)
        result['avg_leaf_temp'] = round(result['avg_effective_temp'], 2)
        result['total_precipitation'] = round(result['total_precipitation'], 2)
        wind_kmh = result.get('max_wind_speed_10m')
        if wind_kmh is not None and not pd.isna(wind_kmh):
            result['max_wind_speed_10m'] = round(wind_kmh, 1)
        else:
            result['max_wind_speed_10m'] = None
        result['avg_relative_humidity_2m'] = round(result['avg_relative_humidity_2m'], 2)
        result['wet_hours'] = int(result['wet_hours'])
        result['longest_wet_run'] = int(result['longest_wet_run'])
        result['continuous_wet_at_eod'] = int(result.get('continuous_wet_at_eod', 0))
        result['had_gap_break'] = bool(result['had_gap_break'])
        weather_code = result.get('weather_code')
        if weather_code is not None and not pd.isna(weather_code):
            result['weather_code'] = int(weather_code)
        else:
            result['weather_code'] = None
        if result['had_gap_break']:
            result['wet_hours_note'] = "Dry gap ≥ 4 hours occurred today; longest wet run reset afterward."

    return jsonify(results)

# --- Server Execution ---
if __name__ == '__main__':
    app.run(debug=True)
