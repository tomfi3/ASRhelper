# ASR Helper

Automates data extraction and report generation for the Annual Status Report (ASR) air quality monitoring data returns for Richmond upon Thames (and future: Wandsworth, Merton).

## What it does

- Pulls NO2 data from the [London Air Quality Network API](https://api.erg.ic.ac.uk/AirQuality/help)
- Extracts hourly automatic analyser data and diffusion tube measurements
- Generates bias adjustment questionnaire Excel workbooks per monitoring station
- Calculates monthly means, annual statistics, data capture rates, and local bias adjustment factors

## Richmond Monitoring Stations

| Code | Name | Type |
|------|------|------|
| RI1 | Castelnau | Roadside |
| RI2 | Barnes Wetlands | Suburban Background |
| RHI | Richmond | Roadside |

## Usage

```bash
pip install -r requirements.txt
python main.py --year 2024 --sites RI1,RI2,RHI
```

Output Excel files are written to `output/`.

## Excel File Structure

Each workbook contains 4 sheets:

1. **Site & Study Info** - Station details and diffusion tube metadata
2. **Monthly Data** - Side-by-side diffusion tube vs automatic analyser NO2 concentrations
3. **Bias Adjustment** - Local bias adjustment factor calculation
4. **Annual Statistics** - Annual means, data capture, exceedances

## Next Steps After Generation

1. Fill in tube supplier/laboratory and preparation method in Sheet 1
2. Add tube exposure start/end dates in Sheet 2
3. If local bias factor cannot be calculated (<9 valid months), use the [national bias adjustment factor](https://laqm.defra.gov.uk/air-quality/air-quality-assessment/national-bias/)
