"""Client for the London Air Quality Network (LAQN) API at api.erg.ic.ac.uk.

Based on API patterns from https://github.com/tomfi3/SensorsAPI
"""

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


def _get(url):
    """Make a GET request to the London Air API."""
    logger.info(f"Requesting: {url}")
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    return response.json()


def get_site_species(group_name="London"):
    """Get all monitoring sites and their species for a group."""
    url = f"{BASE_URL}/Information/MonitoringSiteSpecies/GroupName={group_name}/Json"
    return _get(url)


def get_hourly_data(site_code, species_code, start_date, end_date):
    """Get hourly monitoring data for a site and species.

    Args:
        site_code: e.g. 'RI1'
        species_code: e.g. 'NO2'
        start_date: 'YYYY-MM-DD' format
        end_date: 'YYYY-MM-DD' format
    """
    url = (
        f"{BASE_URL}/Data/SiteSpecies"
        f"/SiteCode={site_code}/SpeciesCode={species_code}"
        f"/StartDate={start_date}/EndDate={end_date}/Json"
    )
    return _get(url)


def get_annual_report(site_code, year):
    """Get annual monitoring report for a site and year.

    Returns monthly and annual means from the official LAQN report.
    """
    url = f"{BASE_URL}/Annual/MonitoringReport/SiteCode={site_code}/Year={year}/json"
    return _get(url)


def get_diffusion_tube_data(site_code, mon_type="DT"):
    """Get diffusion tube data for a site.

    Args:
        site_code: site code e.g. 'RI1'
        mon_type: monitoring type, 'DT' for diffusion tubes
    """
    url = f"{BASE_URL}/Data/DiffusionTube/code={site_code}/montype={mon_type}/Json"
    return _get(url)


def get_annual_objectives(group_name="Richmond", year=None):
    """Get annual monitoring objectives for a group/borough."""
    endpoint = f"Annual/MonitoringObjective/GroupName={group_name}"
    if year:
        endpoint += f"/Year={year}"
    url = f"{BASE_URL}/{endpoint}/Json"
    return _get(url)


def extract_hourly_values(api_response):
    """Extract hourly measurement values from API response.

    The API wraps hourly data under either 'RawAQData' or 'AirQualityData'.
    Each record has @MeasurementDateGMT (or @DateTime/@Date) and @Value.
    """
    records = []
    try:
        raw_data = (
            api_response.get("RawAQData")
            or api_response.get("AirQualityData")
            or {}
        )
        data_entries = raw_data.get("Data", [])
        if isinstance(data_entries, dict):
            data_entries = [data_entries]
        for entry in data_entries:
            date_str = (
                entry.get("@MeasurementDateGMT")
                or entry.get("@DateTime")
                or entry.get("@Date", "")
            )
            value = entry.get("@Value") or entry.get("@Concentration", "")
            if value and str(value).strip():
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


def extract_annual_report_data(api_response, species_code="NO2"):
    """Extract monthly and annual means from the Annual MonitoringReport endpoint.

    Returns dict with 'annual_mean' and 'monthly' {month_num: value}.
    """
    result = {"annual_mean": None, "monthly": {}}
    try:
        site_report = api_response.get("SiteReport", {})
        report_items = site_report.get("ReportItem", [])
        if isinstance(report_items, dict):
            report_items = [report_items]

        for item in report_items:
            if item.get("@SpeciesCode") != species_code:
                continue
            # ReportItem type 7 = means
            annual_val = item.get("@Annual", "")
            if annual_val and str(annual_val).strip():
                try:
                    result["annual_mean"] = float(annual_val)
                except (ValueError, TypeError):
                    pass

            for month_num in range(1, 13):
                month_key = f"@Month{month_num}"
                val = item.get(month_key, "")
                if val and str(val).strip():
                    try:
                        result["monthly"][month_num] = float(val)
                    except (ValueError, TypeError):
                        pass
    except (AttributeError, TypeError) as e:
        logger.warning(f"Failed to extract annual report data: {e}")
    return result


def extract_diffusion_tube_values(api_response):
    """Extract diffusion tube monthly values from API response."""
    records = []
    try:
        # Try multiple possible response structures
        dt_data = (
            api_response.get("DiffusionTubeData")
            or api_response.get("RawDiffusionTubeData")
            or api_response
        )
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
                if value and str(value).strip():
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
    import calendar
    expected_hours = 366 * 24 if calendar.isleap(year) else 365 * 24

    return {
        "annual_mean": round(sum(values) / len(values), 1),
        "data_capture": round((len(values) / expected_hours) * 100, 1),
        "max_hourly": round(max(values), 1),
        "hours_above_200": sum(1 for v in values if v > 200),
        "total_hours": len(values),
    }
