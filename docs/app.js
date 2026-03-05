// ASR Helper - London Air Quality Data Extraction & Bias Adjustment
// Calls the London Air API (api.erg.ic.ac.uk) directly from the browser.

const API_BASE = "https://api.erg.ic.ac.uk/AirQuality";

const SITES = {
    RI1: { name: "Richmond Upon Thames - Castelnau", type: "Roadside", location: "Castelnau, Barnes", borough: "Richmond upon Thames" },
    RI2: { name: "Richmond Upon Thames - Barnes Wetlands", type: "Suburban Background", location: "WWT London Wetland Centre, Barnes", borough: "Richmond upon Thames" },
    RHI: { name: "Richmond Upon Thames - Richmond", type: "Roadside", location: "Opposite Richmond Train Station", borough: "Richmond upon Thames" },
};

const MONTHS = ["January","February","March","April","May","June","July","August","September","October","November","December"];

// State
let siteData = {};
let activeSite = null;

// ── API calls ──

async function fetchJSON(url) {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`API error ${resp.status}: ${url}`);
    return resp.json();
}

async function fetchHourlyData(siteCode, year) {
    const url = `${API_BASE}/Data/SiteSpecies/SiteCode=${siteCode}/SpeciesCode=NO2/StartDate=${year}-01-01/EndDate=${year}-12-31/Json`;
    const data = await fetchJSON(url);
    const raw = data.RawAQData || data.AirQualityData || {};
    let entries = raw.Data || [];
    if (!Array.isArray(entries)) entries = [entries];

    const records = [];
    for (const e of entries) {
        const dateStr = e["@MeasurementDateGMT"] || e["@DateTime"] || e["@Date"] || "";
        const valStr = e["@Value"] || e["@Concentration"] || "";
        if (valStr && valStr.trim()) {
            const val = parseFloat(valStr);
            if (!isNaN(val)) {
                records.push({ datetime: new Date(dateStr), value: val });
            }
        }
    }
    return records;
}

async function fetchAnnualReport(siteCode, year) {
    const url = `${API_BASE}/Annual/MonitoringReport/SiteCode=${siteCode}/Year=${year}/json`;
    const data = await fetchJSON(url);
    const report = data.SiteReport || {};
    let items = report.ReportItem || [];
    if (!Array.isArray(items)) items = [items];

    const result = { annual: null, monthly: {} };
    for (const item of items) {
        if (item["@SpeciesCode"] !== "NO2") continue;
        if (String(item["@ReportItem"]) !== "7") continue;
        if (!String(item["@ReportItemName"] || "").startsWith("Mean:")) continue;

        const annual = item["@Annual"];
        if (annual && annual !== "-999") {
            const v = parseFloat(annual);
            if (!isNaN(v)) result.annual = v;
        }
        for (let m = 1; m <= 12; m++) {
            const val = item[`@Month${m}`];
            if (val && val !== "-999") {
                const v = parseFloat(val);
                if (!isNaN(v)) result.monthly[m] = v;
            }
        }
    }
    return result;
}

async function fetchDiffusionTubeData(siteCode, year) {
    const url = `${API_BASE}/Data/DiffusionTube/code=${siteCode}/montype=DT/Json`;
    const data = await fetchJSON(url);
    const dtData = data.DiffusionTubeData || data.RawDiffusionTubeData || data;
    let sites = dtData.Site || [];
    if (!Array.isArray(sites)) sites = [sites];

    const monthly = {};
    for (const site of sites) {
        let measurements = site.Measurement || [];
        if (!Array.isArray(measurements)) measurements = [measurements];
        for (const m of measurements) {
            if (parseInt(m["@Year"]) !== year) continue;
            const val = parseFloat(m["@Value"]);
            if (!isNaN(val)) {
                monthly[parseInt(m["@Month"])] = val;
            }
        }
    }
    return monthly;
}

// ── Calculations ──

function calcMonthlyMeans(records) {
    const byMonth = {};
    for (const r of records) {
        const m = r.datetime.getMonth() + 1;
        if (!byMonth[m]) byMonth[m] = [];
        byMonth[m].push(r.value);
    }

    const result = {};
    for (const [m, vals] of Object.entries(byMonth)) {
        const year = records[0].datetime.getFullYear();
        const daysInMonth = new Date(year, parseInt(m), 0).getDate();
        const expectedHours = daysInMonth * 24;
        result[m] = {
            mean: vals.reduce((a, b) => a + b, 0) / vals.length,
            count: vals.length,
            dataCapture: (vals.length / expectedHours) * 100,
        };
    }
    return result;
}

function calcAnnualStats(records) {
    if (!records.length) return { annualMean: null, dataCapture: 0, maxHourly: null, hoursAbove200: 0, totalHours: 0 };
    const vals = records.map(r => r.value);
    const year = records[0].datetime.getFullYear();
    const isLeap = (year % 4 === 0 && year % 100 !== 0) || (year % 400 === 0);
    const expected = (isLeap ? 366 : 365) * 24;
    return {
        annualMean: +(vals.reduce((a, b) => a + b, 0) / vals.length).toFixed(1),
        dataCapture: +((vals.length / expected) * 100).toFixed(1),
        maxHourly: +Math.max(...vals).toFixed(1),
        hoursAbove200: vals.filter(v => v > 200).length,
        totalHours: vals.length,
    };
}

// ── Main fetch ──

async function fetchData() {
    const year = parseInt(document.getElementById("year").value);
    const siteSelect = document.getElementById("sites");
    const selectedSites = Array.from(siteSelect.selectedOptions).map(o => o.value);

    if (!selectedSites.length) {
        showStatus("Select at least one site", "error");
        return;
    }

    const btn = document.getElementById("fetchBtn");
    btn.disabled = true;
    showStatus(`<span class="spinner"></span> Fetching data for ${selectedSites.join(", ")} (${year})...`, "loading");
    siteData = {};

    try {
        for (const siteCode of selectedSites) {
            showStatus(`<span class="spinner"></span> Fetching ${siteCode}...`, "loading");
            const site = { code: siteCode, info: SITES[siteCode] || {}, year };

            // Fetch hourly data
            try {
                const hourly = await fetchHourlyData(siteCode, year);
                site.hourlyRecords = hourly;
                site.monthlyAuto = calcMonthlyMeans(hourly);
                site.annualStats = calcAnnualStats(hourly);
            } catch (e) {
                console.warn(`Hourly data failed for ${siteCode}:`, e);
                site.hourlyRecords = [];
                site.monthlyAuto = {};
                site.annualStats = { annualMean: null, dataCapture: 0, maxHourly: null, hoursAbove200: 0, totalHours: 0 };
            }

            // Fetch annual report (fallback/supplement)
            try {
                const report = await fetchAnnualReport(siteCode, year);
                site.reportData = report;
                // Use report data as fallback if no hourly
                if (!site.hourlyRecords.length && Object.keys(report.monthly).length) {
                    for (const [m, val] of Object.entries(report.monthly)) {
                        site.monthlyAuto[m] = { mean: val, count: null, dataCapture: null };
                    }
                }
                if (!site.annualStats.annualMean && report.annual != null) {
                    site.annualStats.annualMean = report.annual;
                }
            } catch (e) {
                console.warn(`Annual report failed for ${siteCode}:`, e);
                site.reportData = { annual: null, monthly: {} };
            }

            // Fetch diffusion tube data
            try {
                site.monthlyDT = await fetchDiffusionTubeData(siteCode, year);
            } catch (e) {
                console.warn(`Diffusion tube data failed for ${siteCode}:`, e);
                site.monthlyDT = {};
            }

            siteData[siteCode] = site;
        }

        showStatus(`Data loaded for ${Object.keys(siteData).length} site(s)`, "success");
        renderResults();
    } catch (e) {
        showStatus(`Error: ${e.message}`, "error");
        console.error(e);
    } finally {
        btn.disabled = false;
    }
}

// ── Rendering ──

function showStatus(msg, type) {
    const el = document.getElementById("status");
    el.innerHTML = msg;
    el.className = `status ${type}`;
}

function renderResults() {
    const codes = Object.keys(siteData);
    if (!codes.length) return;

    document.getElementById("results").style.display = "block";

    // Site selector buttons
    const selector = document.getElementById("siteSelector");
    selector.innerHTML = codes.map(c =>
        `<div class="site-btn ${c === codes[0] ? 'active' : ''}" onclick="selectSite('${c}')">${c} - ${SITES[c]?.name?.split(" - ")[1] || c}</div>`
    ).join("");

    activeSite = codes[0];
    renderSiteData(activeSite);
}

function selectSite(code) {
    activeSite = code;
    document.querySelectorAll(".site-btn").forEach(b => b.classList.remove("active"));
    document.querySelector(`.site-btn[onclick="selectSite('${code}')"]`).classList.add("active");
    renderSiteData(code);
}

function switchTab(name) {
    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach(t => t.classList.remove("active"));
    event.target.classList.add("active");
    document.getElementById(`tab-${name}`).classList.add("active");
}

function renderSiteData(code) {
    const s = siteData[code];
    if (!s) return;
    renderSiteInfo(s);
    renderMonthlyData(s);
    renderBiasAdjustment(s);
    renderAnnualStats(s);
}

function renderSiteInfo(s) {
    const info = s.info;
    document.getElementById("tab-info").innerHTML = `
        <h3>Site Details</h3>
        <dl class="info-grid">
            <dt>Site Code</dt><dd>${s.code}</dd>
            <dt>Site Name</dt><dd>${info.name || ""}</dd>
            <dt>Site Type</dt><dd>${info.type || ""}</dd>
            <dt>Location</dt><dd>${info.location || ""}</dd>
            <dt>Borough</dt><dd>${info.borough || ""}</dd>
            <dt>Monitoring Year</dt><dd>${s.year}</dd>
        </dl>
        <h3>Diffusion Tube Details</h3>
        <dl class="info-grid">
            <dt>Tube Supplier/Lab</dt><dd><em>To be completed</em></dd>
            <dt>Preparation Method</dt><dd><em>To be completed</em></dd>
            <dt>Tube Type</dt><dd>Palmes-type</dd>
            <dt>Analysis Method</dt><dd>Spectrophotometry</dd>
            <dt>Exposure Period</dt><dd>Monthly (~4-5 weeks)</dd>
        </dl>
        <h3>Data Source</h3>
        <p>Automatic analyser data from <a href="https://www.londonair.org.uk" target="_blank">London Air Quality Network API</a></p>
    `;
}

function fmt(v, dp = 1) {
    if (v == null || isNaN(v)) return "—";
    return Number(v).toFixed(dp);
}

function renderMonthlyData(s) {
    let rows = "";
    const tubeVals = [], autoVals = [];

    for (let m = 1; m <= 12; m++) {
        const dt = s.monthlyDT[m];
        const auto = s.monthlyAuto[m];
        const autoMean = auto?.mean;
        const dc = auto?.dataCapture;
        const ratio = (dt != null && autoMean != null && autoMean > 0) ? (dt / autoMean) : null;
        const diff = (dt != null && autoMean != null) ? (dt - autoMean) : null;
        const dcClass = dc != null && dc < 75 ? "warn" : "";

        if (dt != null) tubeVals.push(dt);
        if (autoMean != null) autoVals.push(autoMean);

        rows += `<tr>
            <td class="label">${MONTHS[m-1]}</td>
            <td>${fmt(dt)}</td>
            <td>${fmt(autoMean)}</td>
            <td class="${dcClass}">${fmt(dc)}</td>
            <td>${fmt(ratio, 2)}</td>
            <td>${fmt(diff)}</td>
        </tr>`;
    }

    const tubeMean = tubeVals.length ? tubeVals.reduce((a,b) => a+b, 0) / tubeVals.length : null;
    const autoMean = autoVals.length ? autoVals.reduce((a,b) => a+b, 0) / autoVals.length : null;
    const tubeDC = ((tubeVals.length / 12) * 100);

    rows += `<tr class="summary-row">
        <td class="label">Annual Mean</td>
        <td>${fmt(tubeMean)}</td>
        <td>${fmt(autoMean)}</td>
        <td>—</td><td>—</td><td>—</td>
    </tr>`;
    rows += `<tr class="summary-row">
        <td class="label">Data Capture (%)</td>
        <td>${fmt(tubeDC)}</td>
        <td>—</td><td>—</td><td>—</td><td>—</td>
    </tr>`;

    document.getElementById("tab-monthly").innerHTML = `
        <h3>Monthly NO2 Concentrations (µg/m³) - ${s.code} - ${s.year}</h3>
        <table>
            <tr><th>Month</th><th>Diffusion Tube</th><th>Auto Analyser</th><th>Data Capture %</th><th>Tube/Auto Ratio</th><th>Difference</th></tr>
            ${rows}
        </table>
        <p style="margin-top:1rem;font-size:0.8rem;color:#666;">
            Data capture &lt;75% highlighted in red — annualisation may be required.
        </p>
    `;
}

function renderBiasAdjustment(s) {
    let rows = "";
    const ratios = [];

    for (let m = 1; m <= 12; m++) {
        const dt = s.monthlyDT[m];
        const auto = s.monthlyAuto[m];
        const autoMean = auto?.mean;
        const dc = auto?.dataCapture;
        let ratio = null, include = "No data";
        let cls = "";

        if (dt != null && autoMean != null && dt > 0) {
            ratio = autoMean / dt;
            if (dc == null || dc >= 75) {
                include = "Yes";
                ratios.push(ratio);
            } else {
                include = "No (low DC)";
                cls = "warn";
            }
        } else {
            cls = "warn";
        }

        rows += `<tr>
            <td class="label">${MONTHS[m-1]}</td>
            <td>${fmt(dt)}</td>
            <td>${fmt(autoMean)}</td>
            <td>${fmt(ratio, 3)}</td>
            <td class="${cls}">${include}</td>
        </tr>`;
    }

    let resultHTML = "";
    if (ratios.length > 0) {
        const meanRatio = ratios.reduce((a,b) => a+b, 0) / ratios.length;
        let stdDev = 0, ci = 0;
        if (ratios.length > 1) {
            const variance = ratios.reduce((sum, r) => sum + (r - meanRatio) ** 2, 0) / (ratios.length - 1);
            stdDev = Math.sqrt(variance);
            ci = 2.0 * stdDev / Math.sqrt(ratios.length);
        }

        const tubeVals = Object.values(s.monthlyDT);
        const rawMean = tubeVals.length ? tubeVals.reduce((a,b) => a+b, 0) / tubeVals.length : null;
        const adjMean = rawMean != null ? rawMean * meanRatio : null;

        resultHTML = `
            <h3>Results</h3>
            <table>
                <tr class="result"><td class="label">Valid paired months</td><td>${ratios.length}</td></tr>
                <tr class="result"><td class="label">Mean Auto/Tube ratio (bias factor)</td><td>${meanRatio.toFixed(3)}</td></tr>
                <tr class="result"><td class="label">Std deviation of ratios</td><td>${ratios.length > 1 ? stdDev.toFixed(3) : "N/A"}</td></tr>
                <tr class="result"><td class="label">~95% CI</td><td>${ratios.length > 1 ? "±" + ci.toFixed(3) : "N/A"}</td></tr>
                ${rawMean != null ? `
                <tr><td class="label" colspan="2" style="height:8px;border:none;"></td></tr>
                <tr class="result"><td class="label">Raw tube annual mean (µg/m³)</td><td>${fmt(rawMean)}</td></tr>
                <tr class="result"><td class="label">Bias adjustment factor</td><td>${meanRatio.toFixed(3)}</td></tr>
                <tr class="result"><td class="label">Bias-adjusted annual mean (µg/m³)</td><td>${fmt(adjMean)}</td></tr>
                <tr class="result"><td class="label">Annual mean objective (µg/m³)</td><td>40</td></tr>
                <tr class="${adjMean <= 40 ? 'good' : 'warn'} result"><td class="label">Objective met?</td><td>${adjMean <= 40 ? "Yes" : "No"}</td></tr>
                ` : ""}
            </table>
        `;
    } else {
        resultHTML = `
            <h3>Results</h3>
            <p>Insufficient paired data for local bias calculation. Use the
            <a href="https://laqm.defra.gov.uk/air-quality/air-quality-assessment/national-bias/" target="_blank">national bias adjustment factor</a>
            matching your tube laboratory and preparation method.</p>
        `;
    }

    document.getElementById("tab-bias").innerHTML = `
        <h3>Bias Adjustment Factor Calculation - ${s.code} - ${s.year}</h3>
        <p style="margin-bottom:1rem;font-size:0.9rem;color:#555;">
            Local bias adjustment factor = Mean of (monthly auto analyser / monthly diffusion tube) ratios
        </p>
        <table>
            <tr><th>Month</th><th>Tube (µg/m³)</th><th>Auto (µg/m³)</th><th>Auto/Tube Ratio</th><th>Include?</th></tr>
            ${rows}
        </table>
        ${resultHTML}
    `;
}

function renderAnnualStats(s) {
    const st = s.annualStats;
    const metMean = st.annualMean != null ? (st.annualMean <= 40 ? "Yes" : "No") : "N/A";
    const metHours = st.hoursAbove200 != null ? (st.hoursAbove200 <= 18 ? "Yes" : "No") : "N/A";

    let monthlyRows = "";
    for (let m = 1; m <= 12; m++) {
        const auto = s.monthlyAuto[m];
        const dcClass = auto?.dataCapture != null && auto.dataCapture < 75 ? "warn" : "";
        monthlyRows += `<tr>
            <td class="label">${MONTHS[m-1]}</td>
            <td>${fmt(auto?.mean)}</td>
            <td class="${dcClass}">${fmt(auto?.dataCapture)}</td>
            <td>${auto?.count != null ? auto.count : "—"}</td>
        </tr>`;
    }

    document.getElementById("tab-annual").innerHTML = `
        <h3>NO2 Automatic Analyser Statistics - ${s.code} - ${s.year}</h3>
        <table>
            <tr><th>Statistic</th><th>Value</th><th>Objective</th><th>Met?</th></tr>
            <tr><td class="label">Annual mean NO2 (µg/m³)</td><td>${fmt(st.annualMean)}</td><td>40 µg/m³</td><td class="${metMean === 'No' ? 'warn' : ''}">${metMean}</td></tr>
            <tr><td class="label">Max hourly NO2 (µg/m³)</td><td>${fmt(st.maxHourly)}</td><td>200 µg/m³ (≤18 exc.)</td><td>—</td></tr>
            <tr><td class="label">Hours > 200 µg/m³</td><td>${st.hoursAbove200 != null ? st.hoursAbove200 : "—"}</td><td>≤18 per year</td><td class="${metHours === 'No' ? 'warn' : ''}">${metHours}</td></tr>
            <tr><td class="label">Data capture (%)</td><td>${fmt(st.dataCapture)}</td><td>≥75%</td><td>—</td></tr>
            <tr><td class="label">Total valid hours</td><td>${st.totalHours != null ? st.totalHours : "—"}</td><td>—</td><td>—</td></tr>
        </table>

        <h3>Monthly Breakdown - Automatic Analyser NO2</h3>
        <table>
            <tr><th>Month</th><th>Mean (µg/m³)</th><th>Data Capture (%)</th><th>Valid Hours</th></tr>
            ${monthlyRows}
        </table>
    `;
}

// ── Export ──

function exportCSV() {
    if (!activeSite || !siteData[activeSite]) return;
    const s = siteData[activeSite];
    let csv = `Bias Adjustment Data - ${s.code} - ${s.year}\n\n`;
    csv += "Month,Diffusion Tube (µg/m³),Auto Analyser (µg/m³),Data Capture (%),Tube/Auto Ratio,Auto/Tube Ratio\n";

    for (let m = 1; m <= 12; m++) {
        const dt = s.monthlyDT[m];
        const auto = s.monthlyAuto[m];
        const autoMean = auto?.mean;
        const dc = auto?.dataCapture;
        const tubeAutoRatio = (dt != null && autoMean != null && autoMean > 0) ? (dt / autoMean).toFixed(3) : "";
        const autoTubeRatio = (dt != null && autoMean != null && dt > 0) ? (autoMean / dt).toFixed(3) : "";
        csv += `${MONTHS[m-1]},${dt != null ? dt.toFixed(1) : ""},${autoMean != null ? autoMean.toFixed(1) : ""},${dc != null ? dc.toFixed(1) : ""},${tubeAutoRatio},${autoTubeRatio}\n`;
    }

    csv += `\nAnnual Stats\n`;
    csv += `Annual Mean (auto),${fmt(s.annualStats.annualMean)}\n`;
    csv += `Data Capture (%),${fmt(s.annualStats.dataCapture)}\n`;
    csv += `Max Hourly,${fmt(s.annualStats.maxHourly)}\n`;
    csv += `Hours > 200,${s.annualStats.hoursAbove200}\n`;

    const blob = new Blob([csv], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `BiasAdjustment_${s.code}_${s.year}.csv`;
    a.click();
}
