#!/usr/bin/env python3
"""ASR Helper - Extract air quality data and generate bias adjustment questionnaires.

Pulls data from the London Air Quality Network API and generates
bias adjustment questionnaire Excel files for the Annual Status Report.

Usage:
    python main.py [--year YEAR] [--sites SITE1,SITE2,...] [--output DIR]
"""

import argparse
import logging
import sys

from src.london_air_api import (
    RICHMOND_SITES,
    get_hourly_data,
    get_annual_report,
    get_diffusion_tube_data,
    extract_hourly_values,
    extract_annual_report_data,
    extract_diffusion_tube_values,
    calculate_monthly_means,
    calculate_annual_stats,
)
from src.bias_adjustment import generate_bias_adjustment_workbook

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DEFAULT_YEAR = 2024
DEFAULT_SITES = ["RI1", "RI2", "RHI"]
OUTPUT_DIR = "output"


def fetch_automatic_analyser_data(site_code, year):
    """Fetch NO2 data from automatic analyser via hourly endpoint.

    Falls back to the Annual MonitoringReport endpoint if hourly data
    is unavailable or has low data capture.
    """
    logger.info(f"Fetching automatic analyser NO2 data for {site_code}, year {year}...")

    monthly_means = {}
    annual_stats = {}
    start_date = f"{year}-01-01"
    end_date = f"{year}-12-31"

    # Try hourly data first
    try:
        response = get_hourly_data(site_code, "NO2", start_date, end_date)
        hourly_records = extract_hourly_values(response)

        if hourly_records:
            monthly_means = calculate_monthly_means(hourly_records)
            annual_stats = calculate_annual_stats(hourly_records)
            logger.info(
                f"  {site_code}: {len(hourly_records)} hourly records, "
                f"annual mean = {annual_stats.get('annual_mean', 'N/A')} µg/m³, "
                f"data capture = {annual_stats.get('data_capture', 'N/A')}%"
            )
        else:
            logger.warning(f"  {site_code}: No hourly NO2 data returned")
    except Exception as e:
        logger.warning(f"  {site_code}: Hourly data fetch failed: {e}")

    # Supplement/fallback with annual report data
    try:
        report_response = get_annual_report(site_code, year)
        report_data = extract_annual_report_data(report_response, species_code="NO2")

        if report_data["monthly"] and not monthly_means:
            logger.info(f"  {site_code}: Using annual report monthly means as fallback")
            for month_num, val in report_data["monthly"].items():
                monthly_means[month_num] = {
                    "mean": val,
                    "count": None,
                    "data_capture": None,
                }

        if report_data["annual_mean"] is not None and not annual_stats:
            logger.info(
                f"  {site_code}: Using annual report mean: "
                f"{report_data['annual_mean']} µg/m³"
            )
            annual_stats = {
                "annual_mean": report_data["annual_mean"],
                "data_capture": None,
                "max_hourly": None,
                "hours_above_200": None,
                "total_hours": None,
            }
    except Exception as e:
        logger.warning(f"  {site_code}: Annual report fetch failed: {e}")

    return monthly_means, annual_stats


def fetch_diffusion_tube_data(site_code, year):
    """Fetch diffusion tube NO2 data and extract monthly values."""
    logger.info(f"Fetching diffusion tube data for {site_code}, year {year}...")

    try:
        response = get_diffusion_tube_data(site_code)
        all_records = extract_diffusion_tube_values(response)

        # Filter to requested year
        year_records = [r for r in all_records if r["year"] == year]

        monthly_dt = {}
        for rec in year_records:
            monthly_dt[rec["month"]] = rec["value"]

        if monthly_dt:
            logger.info(f"  {site_code}: {len(monthly_dt)} months of diffusion tube data")
        else:
            logger.warning(f"  {site_code}: No diffusion tube data for {year}")

        return monthly_dt

    except Exception as e:
        logger.error(f"Failed to fetch diffusion tube data for {site_code}: {e}")
        return {}


def process_site(site_code, year, output_dir):
    """Process a single monitoring site: fetch data and generate workbook."""
    site_info = RICHMOND_SITES.get(site_code, {
        "name": site_code,
        "site_type": "Unknown",
        "location": "Unknown",
        "borough": "Richmond upon Thames",
    })

    logger.info(f"\n{'='*60}")
    logger.info(f"Processing site: {site_code} - {site_info['name']}")
    logger.info(f"{'='*60}")

    # Fetch data from API
    monthly_auto, annual_stats = fetch_automatic_analyser_data(site_code, year)
    monthly_dt = fetch_diffusion_tube_data(site_code, year)

    # If no annual_stats from any source, create empty
    if not annual_stats:
        annual_stats = {
            "annual_mean": None,
            "data_capture": 0,
            "max_hourly": None,
            "hours_above_200": 0,
            "total_hours": 0,
        }

    # Generate workbook
    filepath = generate_bias_adjustment_workbook(
        site_code=site_code,
        site_info=site_info,
        year=year,
        monthly_auto=monthly_auto,
        monthly_dt=monthly_dt,
        annual_stats=annual_stats,
        output_dir=output_dir,
    )

    return filepath


def main():
    parser = argparse.ArgumentParser(
        description="Generate bias adjustment questionnaire Excel files for ASR reporting"
    )
    parser.add_argument(
        "--year",
        type=int,
        default=DEFAULT_YEAR,
        help=f"Monitoring year (default: {DEFAULT_YEAR})",
    )
    parser.add_argument(
        "--sites",
        type=str,
        default=",".join(DEFAULT_SITES),
        help=f"Comma-separated site codes (default: {','.join(DEFAULT_SITES)})",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=OUTPUT_DIR,
        help=f"Output directory (default: {OUTPUT_DIR})",
    )
    args = parser.parse_args()

    sites = [s.strip() for s in args.sites.split(",")]
    year = args.year
    output_dir = args.output

    logger.info("ASR Helper - Bias Adjustment Questionnaire Generator")
    logger.info(f"Year: {year}")
    logger.info(f"Sites: {', '.join(sites)}")
    logger.info(f"Output: {output_dir}/")

    generated_files = []
    errors = []

    for site_code in sites:
        try:
            filepath = process_site(site_code, year, output_dir)
            generated_files.append(filepath)
            logger.info(f"  -> Generated: {filepath}")
        except Exception as e:
            logger.error(f"  -> FAILED for {site_code}: {e}")
            errors.append((site_code, str(e)))

    # Summary
    logger.info(f"\n{'='*60}")
    logger.info("SUMMARY")
    logger.info(f"{'='*60}")
    logger.info(f"Generated {len(generated_files)} file(s):")
    for f in generated_files:
        logger.info(f"  {f}")
    if errors:
        logger.warning(f"\n{len(errors)} error(s):")
        for site, err in errors:
            logger.warning(f"  {site}: {err}")

    logger.info("\nNext steps:")
    logger.info(f"1. Review the generated Excel files in {output_dir}/")
    logger.info("2. Fill in the tube supplier/laboratory and preparation method")
    logger.info("3. Add diffusion tube exposure start/end dates if available")
    logger.info("4. Apply national bias adjustment factor if local factor unavailable")
    logger.info("   Download from: https://laqm.defra.gov.uk/air-quality/air-quality-assessment/national-bias/")

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
