"""Client for the London Air Quality Network (LAQN) API at api.erg.ic.ac.uk."""

import requests
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

BASE_URL = "https://api.erg.ic.ac.uk/AirQuality"

# Richmond monitoring stations
RICHMOND_SITES = {
    "RI1": {
        "name": "Richmond Upon Thames - Castelnau",
        "site_type": "Roadside",
        "location": "Castelnau, Barnes",
        "borough": "Richmond upon Thames",
    },
    "RI2": {
        "name": "Richmond Upon Thames - Barnes Wetlands",
        "site_type": "Suburban Background",
        "location": "WWT London Wetland Centre, Barnes",
        "borough": "Richmond upon Thames",
    },
    "RHI": {
        "name": "Richmond Upon Thames - Richmond",
        "site_type": "Roadside",
        "location": "Opposite Richmond Train Station",
        "borough": "Richmond upon Thames",
    },
}


def _get(endpoint, output_format="Json"):
    """Make a GET request to the London Air API."""
    url = f"{BASE_URL}/{endpoint}/{output_format}"
    logger.info(f"Requesting: {url}")
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    if output_format == "Json":
        return response.json()
    return response.text


def get_site_info(group_name="Richmond"):
    """Get monitoring site information for a borough group."""
    return _get(f"Information/MonitoringSites/GroupName={group_name}")


def get_site_species(site_code):
    """Get species/pollutants monitored at a site."""
    return _get(f"Information/MonitoringSiteSpecies/SiteCode={site_code}")


def get_hourly_data(site_code, species_code, start_date, end_date):
    """Get hourly monitoring data for a site and species.

    Args:
        site_code: e.g. 'RI1'
        species_code: e.g. 'NO2'
        start_date: 'YYYY-MM-DD' format
        end_date: 'YYYY-MM-DD' format
    """
    endpoint = (
        f"Data/SiteSpecies/SiteCode={site_code}"
        f"/SpeciesCode={species_code}"
        f"/StartDate={start_date}"
        f"/EndDate={end_date}"
    )
    return _get(endpoint)


def get_daily_data(site_code, species_code, start_date, end_date):
    """Get daily mean monitoring data for a site and species."""
    endpoint = (
        f"Data/SiteSpecies/SiteCode={site_code}"
        f"/SpeciesCode={species_code}"
        f"/StartDate={start_date}"
        f"/EndDate={end_date}"
        f"/Period=Daily"
    )
    return _get(endpoint)


def get_diffusion_tube_data(site_code, mon_type="DT"):
    """Get diffusion tube data for a site.

    Args:
        site_code: site code e.g. 'RI1'
        mon_type: monitoring type, 'DT' for diffusion tubes
    """
    return _get(f"Data/DiffusionTube/code={site_code}/montype={mon_type}")


def get_annual_report(site_code, year):
    """Get annual monitoring report for a site and year."""
    return _get(f"Annual/MonitoringReport/SiteCode={site_code}/Year={year}")


def get_annual_objectives(group_name="Richmond", year=None):
    """Get annual monitoring objectives for a group/borough."""
    endpoint = f"Annual/MonitoringObjective/GroupName={group_name}"
    if year:
        endpoint += f"/Year={year}"
    return _get(endpoint)


def get_species_info(species_code=None):
    """Get information about monitored species/pollutants."""
    if species_code:
        return _get(f"Information/Species/SpeciesCode={species_code}")
    return _get("Information/Species")


def extract_hourly_values(api_response):
    """Extract hourly measurement values from API response into a flat list of dicts."""
    records = []
    try:
        raw_data = api_response.get("RawAQData", {})
        data_entries = raw_data.get("Data", [])
        if isinstance(data_entries, dict):
            data_entries = [data_entries]
        for entry in data_entries:
            date_str = entry.get("@MeasurementDateGMT", "")
            value = entry.get("@Value", "")
            if value and value.strip():
                try:
                    records.append({
                        "datetime": datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S"),
                        "value": float(value),
                    })
                except (ValueError, TypeError):
                    pass
    except (AttributeError, TypeError) as e:
        logger.warning(f"Failed to extract hourly values: {e}")
    return records


def extract_diffusion_tube_values(api_response):
    """Extract diffusion tube monthly values from API response."""
    records = []
    try:
        dt_data = api_response.get("DiffusionTubeData", {})
        sites = dt_data.get("Site", [])
        if isinstance(sites, dict):
            sites = [sites]
        for site in sites:
            measurements = site.get("Measurement", [])
            if isinstance(measurements, dict):
                measurements = [measurements]
            for m in measurements:
                year = m.get("@Year", "")
                month = m.get("@Month", "")
                value = m.get("@Value", "")
                if value and value.strip():
                    try:
                        records.append({
                            "year": int(year),
                            "month": int(month),
                            "value": float(value),
                        })
                    except (ValueError, TypeError):
                        pass
    except (AttributeError, TypeError) as e:
        logger.warning(f"Failed to extract diffusion tube values: {e}")
    return records


def calculate_monthly_means(hourly_records):
    """Calculate monthly mean concentrations from hourly data.

    Returns dict: {month_number: {"mean": value, "count": n, "data_capture": pct}}
    """
    from collections import defaultdict
    import calendar

    monthly = defaultdict(list)
    for rec in hourly_records:
        monthly[rec["datetime"].month].append(rec["value"])

    results = {}
    for month, values in sorted(monthly.items()):
        year = hourly_records[0]["datetime"].year if hourly_records else 2024
        days_in_month = calendar.monthrange(year, month)[1]
        expected_hours = days_in_month * 24
        data_capture = (len(values) / expected_hours) * 100
        results[month] = {
            "mean": sum(values) / len(values),
            "count": len(values),
            "data_capture": round(data_capture, 1),
        }
    return results


def calculate_annual_stats(hourly_records):
    """Calculate annual statistics from hourly data.

    Returns dict with annual_mean, data_capture, max_hourly, hours_above_200, etc.
    """
    if not hourly_records:
        return {
            "annual_mean": None,
            "data_capture": 0,
            "max_hourly": None,
            "hours_above_200": 0,
            "total_hours": 0,
        }

    values = [r["value"] for r in hourly_records]
    year = hourly_records[0]["datetime"].year
    # Expected hours in a year (accounting for leap years)
    import calendar
    expected_hours = 366 * 24 if calendar.isleap(year) else 365 * 24

    return {
        "annual_mean": round(sum(values) / len(values), 1),
        "data_capture": round((len(values) / expected_hours) * 100, 1),
        "max_hourly": round(max(values), 1),
        "hours_above_200": sum(1 for v in values if v > 200),
        "total_hours": len(values),
    }
