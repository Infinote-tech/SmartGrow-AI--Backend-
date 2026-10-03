"""
Generate the SmartGrow AI Power BI project (`scripts/SmartGrow.pbip`) from `scripts/demo_data.py`.

    python scripts/build_powerbi_dashboard.py

Opens in Power BI Desktop (Windows) by double-clicking `scripts/SmartGrow.pbip`. The dark-green report has five pages
(Overview, Moisture & Environment, Irrigation Loop, Faults, Hardware & Crop) with slicers synced across pages. It ships with
the demo dataset embedded, so it works immediately; `powerbi_queries.pq` shows how to point each table at MongoDB.

Re-running this script rewrites `SmartGrow.Report/definition`, `SmartGrow.SemanticModel/definition` and the theme, so
changes made by hand in Power BI Desktop are overwritten -- make lasting changes here.
"""
import json
import shutil
import subprocess
import sys
import time
import uuid
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

from scripts.demo_data import build_demo_dataset  # noqa: E402

REPORT = ROOT / "SmartGrow.Report"
MODEL = ROOT / "SmartGrow.SemanticModel"
SCH = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"

# ---------------------------------------------------------------------------------------------------------------- palette
PAGE_BG, CARD_BG, CARD_BORDER = "#0B241C", "#10382C", "#1D5A45"
TEXT, MUTED = "#E9F6EE", "#8DB7A3"
LIME, GREEN, MID, DEEP, AMBER, RED = "#B6E36B", "#4CC38A", "#2E9E6B", "#1F7A56", "#F2C94C", "#EF6F61"
DATA_COLORS = [LIME, GREEN, MID, "#D6F08A", DEEP, AMBER, "#7FD9B0", RED]


def guid() -> str:
    return str(uuid.uuid4())


def clean(path: Path) -> None:
    """Remove a generated folder.

    OneDrive can leave read-only reparse-point folders that Python's rmtree cannot delete, so on Windows fall back to
    PowerShell's Remove-Item. Stops with a clear message if the folder is still there (e.g. Power BI Desktop has it open).
    """
    shutil.rmtree(path, ignore_errors=True)
    if path.exists() and sys.platform == "win32":
        subprocess.run(["powershell", "-NoProfile", "-Command", f"Remove-Item -Recurse -Force -LiteralPath '{path}'"],
                       capture_output=True, check=False)
    for _ in range(10):
        if not path.exists():
            return
        time.sleep(0.5)
    raise SystemExit(f"Could not remove {path}. Close Power BI Desktop and run this script again.")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def write_json(path: Path, obj) -> None:
    write(path, json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


# ------------------------------------------------------------------------------------------------------ Power Query values
def m_value(value, kind: str) -> str:
    if value is None:
        return "null"
    if kind == "text":
        return '"' + str(value).replace('"', '""') + '"'
    if kind == "bool":
        return "true" if value else "false"
    if kind == "datetime":
        v: datetime = value
        return f"#datetime({v.year}, {v.month}, {v.day}, {v.hour}, {v.minute}, {v.second})"
    if kind == "date":
        v = date.fromisoformat(value) if isinstance(value, str) else value
        return f"#date({v.year}, {v.month}, {v.day})"
    if kind == "int":
        return str(int(value))
    return repr(float(value))


M_TYPE = {"text": "text", "number": "number", "int": "Int64.Type", "datetime": "datetime", "date": "date", "bool": "logical"}
DAX_TYPE = {"text": "string", "number": "double", "int": "int64", "datetime": "dateTime", "date": "dateTime", "bool": "boolean"}
FORMAT = {"datetime": "General Date", "date": "Short Date", "int": "0", "number": "General Number"}


def inline_table(columns: list[tuple[str, str]], rows: list[dict]) -> str:
    header = ", ".join(f"{n} = {M_TYPE[k]}" for n, k in columns)
    body = ",\n".join(
        "            {" + ", ".join(m_value(r.get(n), k) for n, k in columns) + "}" for r in rows)
    return f"#table(\n        type table [{header}],\n        {{\n{body}\n        }})"


# --------------------------------------------------------------------------------------------------------------- TMDL
class Table:
    def __init__(self, name, columns, rows, derived=None, extra_columns=None, measures=None, props=None, sort=None, hidden=()):
        self.name, self.columns, self.rows = name, columns, rows
        self.derived = derived or []  # [(name, kind, m_expression)]
        self.extra_columns = extra_columns or []  # declared columns produced by `derived`
        self.measures = measures or []  # [(name, dax, format)]
        self.props = props or []
        self.sort = sort or {}  # column -> sortByColumn
        self.hidden = set(hidden)

    def m_expression(self) -> str:
        steps = [f"    Source = {inline_table(self.columns, self.rows)}"]
        previous = "Source"
        for i, (name, kind, expr) in enumerate(self.derived):
            step = f"Step{i}"
            m_type = M_TYPE[kind] if kind == "int" else f"type {M_TYPE[kind]}"
            steps.append(f"    {step} = Table.AddColumn({previous}, \"{name}\", each {expr}, {m_type})")
            previous = step
        steps.append(f"    Result = {previous}")
        return "let\n" + ",\n".join(steps) + "\nin\n    Result"

    def tmdl(self) -> str:
        out = [f"table {self.name}"] + [f"\t{p}" for p in self.props] + [f"\tlineageTag: {guid()}", ""]
        for name, dax, fmt in self.measures:
            q = f"'{name}'" if " " in name or "%" in name or "(" in name else name
            lines = dax.strip().split("\n")
            if len(lines) == 1:
                out.append(f"\tmeasure {q} = {lines[0]}")
            else:
                out.append(f"\tmeasure {q} =")
                out += ["\t\t\t" + line for line in lines]
            if fmt:
                out.append(f"\t\tformatString: {fmt}")
            out += [f"\t\tlineageTag: {guid()}", ""]
        for name, kind in self.columns + [(n, k) for n, k, _ in self.derived]:
            q = f"'{name}'" if " " in name else name
            out.append(f"\tcolumn {q}")
            out.append(f"\t\tdataType: {DAX_TYPE[kind]}")
            if kind in FORMAT:
                out.append(f"\t\tformatString: {FORMAT[kind]}")
            if name in self.hidden:
                out.append("\t\tisHidden")
            if name == "Date" and self.name == "Dates":
                out.append("\t\tisKey")
            out.append(f"\t\tlineageTag: {guid()}")
            out.append("\t\tsummarizeBy: none")
            out.append(f"\t\tsourceColumn: {name}")
            if name in self.sort:
                sorter = self.sort[name]
                out.append(f"\t\tsortByColumn: '{sorter}'" if " " in sorter else f"\t\tsortByColumn: {sorter}")
            out.append("")
        expr = "\n".join("\t\t\t\t" + line for line in self.m_expression().split("\n"))
        out += [f"\tpartition {self.name} = m", "\t\tmode: import", "\t\tsource =", expr, "", "\tannotation PBI_ResultType = Table", ""]
        return "\n".join(out)


def L(label: str) -> str:
    """Power Query expression: 'pump_tank_blockage' -> 'Pump Tank Blockage'."""
    return f'Text.Proper(Text.Replace({label}, "_", " "))'


def build_tables(data: dict) -> list[Table]:
    T, N, INT, D, DT, B = "text", "number", "int", "date", "datetime", "bool"
    sensor = Table(
        "SensorData",
        [("sensor_data_id", T), ("timestamp", DT), ("esp32_id", T), ("tray_id", T), ("seed_type", T), ("media_type", T),
         ("temperature", N), ("humidity", N), ("soil_moisture", N), ("light_intensity", N), ("water_level", N),
         ("water_flow_rate", N)],
        data["sensor_data"],
        derived=[("Date", D, "DateTime.Date([timestamp])"), ("Hour", INT, "Time.Hour(DateTime.Time([timestamp]))")],
        measures=[
            ("Avg Moisture", "AVERAGE(SensorData[soil_moisture])", '0.0"%"'),
            ("Latest Moisture", "LASTNONBLANKVALUE(SensorData[timestamp], AVERAGE(SensorData[soil_moisture]))", '0.0"%"'),
            ("Avg Temperature", "AVERAGE(SensorData[temperature])", '0.0"°C"'),
            ("Avg Humidity", "AVERAGE(SensorData[humidity])", '0.0"%"'),
            ("Avg Light", "AVERAGE(SensorData[light_intensity])", '#,0" lux"'),
            ("Avg Water Level", "AVERAGE(SensorData[water_level])", '0.0"%"'),
            ("Readings", "COUNTROWS(SensorData)", "#,0"),
            ("Time In Band %", """VAR inBand =
    SUMX(
        VALUES(Trays[tray_id]),
        VAR lo = [Optimal Min]
        VAR hi = [Optimal Max]
        RETURN CALCULATE(COUNTROWS(SensorData), SensorData[soil_moisture] >= lo, SensorData[soil_moisture] <= hi)
    )
RETURN DIVIDE(inBand, COUNTROWS(SensorData))""", "0.0%"),
        ],
    )
    irrigation = Table(
        "IrrigationLogs",
        [("irrigation_id", T), ("timestamp", DT), ("tray_id", T), ("batch_id", T), ("solenoid_id", T), ("pump_status", T),
         ("irrigation_duration", N), ("water_consumed", N), ("trigger_type", T), ("trigger_reason", T),
         ("ai_recommended", B), ("actual_action", T), ("growth_stage", T), ("pre_irrigation_moisture", N),
         ("post_irrigation_moisture", N), ("post_measured_after_s", INT), ("water_volume", N), ("avg_flow_rate", N),
         ("flow_cv", N), ("expected_response", N), ("actual_response", N), ("response_deviation", N),
         ("model_output_id", T)],
        data["irrigation_logs"],
        derived=[("Date", D, "DateTime.Date([timestamp])"), ("Hour", INT, "Time.Hour(DateTime.Time([timestamp]))"),
                 ("Trigger", T, L("[trigger_type]"))],
        measures=[
            ("Irrigation Events", "COUNTROWS(IrrigationLogs)", "#,0"),
            ("Total Water (mL)", "SUM(IrrigationLogs[water_volume])", '#,0" mL"'),
            ("Avg Volume (mL)", "AVERAGE(IrrigationLogs[water_volume])", '0" mL"'),
            ("Avg Expected Response", "AVERAGE(IrrigationLogs[expected_response])", '0.0" pts"'),
            ("Avg Actual Response", "AVERAGE(IrrigationLogs[actual_response])", '0.0" pts"'),
            ("Avg Response Deviation", "AVERAGE(IrrigationLogs[response_deviation])", '0.0" pts"'),
            ("Avg Flow Rate", "AVERAGE(IrrigationLogs[avg_flow_rate])", '0.00" L/min"'),
            ("AI Recommended %", """DIVIDE(
    CALCULATE(COUNTROWS(IrrigationLogs), IrrigationLogs[ai_recommended] = TRUE()),
    COUNTROWS(IrrigationLogs)
)""", "0%"),
        ],
    )
    outputs = Table(
        "ModelOutputs",
        [("output_id", T), ("timestamp", DT), ("tray_id", T), ("model_name", T), ("model_version", T),
         ("irrigation_recommendation", T), ("decision_volume_ml", N), ("recommendation_confidence", N),
         ("recommended_action", T), ("recommendation_reason", T), ("expected_moisture_change", N),
         ("expected_moisture_after_irrigation", N), ("expected_moisture_lower", N), ("expected_moisture_upper", N),
         ("actual_moisture_after_irrigation", N), ("response_error", N), ("response_confidence", N),
         ("water_response_score", N), ("anomaly_score", N), ("irrigation_id", T), ("batch_id", T), ("growth_stage", T)],
        data["model_outputs"],
        derived=[("Date", D, "DateTime.Date([timestamp])"),
                 ("Decision", T, 'if [irrigation_recommendation] = null then null else ' + L("[irrigation_recommendation]"))],
        measures=[
            ("Policy Decisions", 'CALCULATE(COUNTROWS(ModelOutputs), ModelOutputs[model_name] = "adaptive_irrigation_policy")', "#,0"),
            ("Avg Policy Confidence", 'CALCULATE(AVERAGE(ModelOutputs[recommendation_confidence]), ModelOutputs[model_name] = "adaptive_irrigation_policy")', "0%"),
            ("Avg Water Response Score", "AVERAGE(ModelOutputs[water_response_score])", "0.00"),
            ("Avg Model 1 Confidence", "AVERAGE(ModelOutputs[response_confidence])", "0%"),
            ("Avg Expected After", "AVERAGE(ModelOutputs[expected_moisture_after_irrigation])", '0.0"%"'),
            ("Avg Actual After", "AVERAGE(ModelOutputs[actual_moisture_after_irrigation])", '0.0"%"'),
            ("Avg Response Error", "AVERAGE(ModelOutputs[response_error])", '0.0" pts"'),
        ],
    )
    faults = Table(
        "FaultEvents",
        [("fault_id", T), ("timestamp", DT), ("esp32_id", T), ("tray_id", T), ("fault_type", T), ("fault_source", T),
         ("severity", T), ("sensor_value", N), ("expected_min", N), ("expected_max", N), ("anomaly_score", N),
         ("fault_probability", N), ("detected_by", T), ("recommended_action", T), ("automatic_action", T),
         ("fault_status", T), ("resolved_at", DT), ("resolution_reason", T), ("irrigation_id", T),
         ("response_deviation", N), ("fault_hypothesis", T), ("fault_confidence", N), ("flow_class", T),
         ("response_class", T), ("diagnostic_action", T), ("recovery_action", T), ("recovery_success", B),
         ("injected", B)],
        data["fault_events"],
        derived=[
            ("Date", D, "DateTime.Date([timestamp])"),
            ("Hypothesis", T, L("[fault_hypothesis]")),
            ("Status", T, L("[fault_status]")),
            ("Severity Label", T, L("[severity]")),
            ("Hours To Resolve", N, "if [resolved_at] = null then null else Duration.TotalHours([resolved_at] - [timestamp])"),
        ],
        measures=[
            ("Total Faults", "COUNTROWS(FaultEvents)", "#,0"),
            ("Active Faults", 'CALCULATE(COUNTROWS(FaultEvents), FaultEvents[fault_status] = "active") + 0', "#,0"),
            ("Critical Faults", 'CALCULATE(COUNTROWS(FaultEvents), FaultEvents[severity] = "critical") + 0', "#,0"),
            ("Resolved %", """DIVIDE(
    CALCULATE(COUNTROWS(FaultEvents), FaultEvents[fault_status] = "resolved"),
    COUNTROWS(FaultEvents)
)""", "0%"),
            ("Avg Hours To Resolve", "AVERAGE(FaultEvents[Hours To Resolve])", '0.0" h"'),
            ("Avg Fault Confidence", "AVERAGE(FaultEvents[fault_confidence])", "0%"),
        ],
    )
    hardware = Table(
        "HardwareStatus",
        [("hardware_status_id", T), ("timestamp", DT), ("esp32_id", T), ("overall_system_status", T),
         ("solenoid_1_status", T), ("solenoid_2_status", T), ("solenoid_3_status", T), ("fan_status", T),
         ("motor_status", T), ("water_pump_status", T), ("power_status", T), ("connectivity_status", T)],
        data["hardware_status"],
        derived=[("Date", D, "DateTime.Date([timestamp])"), ("Overall Status", T, L("[overall_system_status]"))],
        measures=[
            ("Snapshots", "COUNTROWS(HardwareStatus)", "#,0"),
            ("Healthy %", 'DIVIDE(CALCULATE(COUNTROWS(HardwareStatus), HardwareStatus[overall_system_status] = "ok"), COUNTROWS(HardwareStatus))', "0%"),
        ],
    )
    batches = Table(
        "CropBatches",
        [("batch_id", T), ("tray_id", T), ("seed_type", T), ("media_type", T), ("planting_date", D),
         ("expected_harvest_date", D), ("harvest_date", D), ("seed_quantity", N), ("batch_status", T)],
        data["crop_batches"],
        measures=[
            ("Active Batches", 'CALCULATE(COUNTROWS(CropBatches), CropBatches[batch_status] <> "harvested") + 0', "#,0"),
            ("Days After Sowing", "DATEDIFF(MIN(CropBatches[planting_date]), CALCULATE(MAX(Dates[Date]), ALL(Dates)), DAY)", "0"),
        ],
    )
    trays = Table(
        "Trays",
        [("tray_id", T), ("tray_name", T), ("seed_type", T), ("media_type", T), ("optimal_min", N), ("optimal_max", N)],
        data["trays"],
        measures=[
            ("Optimal Min", "AVERAGE(Trays[optimal_min])", '0.0"%"'),
            ("Optimal Max", "AVERAGE(Trays[optimal_max])", '0.0"%"'),
        ],
    )
    thresholds = Table(
        "Thresholds",
        [("threshold_id", T), ("seed_type", T), ("media_type", T), ("growth_stage", T), ("parameter", T),
         ("optimal_min", N), ("optimal_max", N), ("warning_min", N), ("warning_max", N), ("critical_min", N),
         ("critical_max", N), ("threshold_version", T), ("effective_from", DT)],
        data["thresholds"],
    )
    dates = Table(
        "Dates", [], [],
        props=["dataCategory: Time"],
    )
    dates.columns = [("Date", D)]
    dates.derived = [
        ("Day Name", T, 'Date.ToText([Date], "ddd", "en-US")'),
        ("Day Number", INT, "Date.DayOfWeek([Date], Day.Monday)"),
        ("Day Label", T, 'Date.ToText([Date], "ddd dd MMM", "en-US")'),
    ]
    dates.sort = {"Day Name": "Day Number", "Day Label": "Date"}
    dates.m_expression = lambda: (  # a calendar covering the demo window
        "let\n    Source = List.Dates(#date(2026, 9, 24), 9, #duration(1, 0, 0, 0)),\n"
        "    AsTable = Table.FromList(Source, Splitter.SplitByNothing(), {\"Date\"}, null, ExtraValues.Error),\n"
        "    Typed = Table.TransformColumnTypes(AsTable, {{\"Date\", type date}}),\n"
        "    Step0 = Table.AddColumn(Typed, \"Day Name\", each Date.ToText([Date], \"ddd\", \"en-US\"), type text),\n"
        "    Step1 = Table.AddColumn(Step0, \"Day Number\", each Date.DayOfWeek([Date], Day.Monday), Int64.Type),\n"
        "    Step2 = Table.AddColumn(Step1, \"Day Label\", each Date.ToText([Date], \"ddd dd MMM\", \"en-US\"), type text),\n"
        "    Result = Step2\nin\n    Result")
    stages = Table(
        "GrowthStages", [("stage_key", T), ("Stage", T), ("Order", INT)],
        [{"stage_key": s, "Stage": s.replace("_", " ").title(), "Order": i} for i, s in enumerate(
            ["germination", "blackout", "early_growth", "active_growth", "pre_harvest"])],
        sort={"Stage": "Order"},
    )
    substrates = Table(
        "Substrates", [("Substrate", T)], [{"Substrate": s} for s in ("cocopeat", "compost", "tissue paper")])

    profile_rows = []
    for sort, (setting, c, t, p) in enumerate([
        ("Dry (irrigate)", "<45%", "<50%", "<40%"), ("Target after watering", "~65%", "~70%", "~60%"),
        ("Good band", "55-75%", "60-80%", "50-70%"), ("Too wet", ">85%", ">90%", ">80%"),
        ("Dose size", "Medium", "Small", "Medium-small"), ("Min interval between doses", "2 h", "45 min", "3 h"),
        ("Max pump run per dose", "10 s", "4 s", "8 s"), ("Moisture check interval", "5 min", "2 min", "5 min"),
    ], start=1):
        for sub, val in (("cocopeat", c), ("tissue paper", t), ("compost", p)):
            profile_rows.append({"Substrate": sub, "Setting": setting, "Value": val, "Sort": sort})
    profile = Table(
        "SubstrateProfile", [("Substrate", T), ("Setting", T), ("Value", T), ("Sort", INT)], profile_rows,
        measures=[("Optimal Value", "SELECTEDVALUE(SubstrateProfile[Value])", None)], sort={"Setting": "Sort"})

    seeds = {"mustard": ("Good", "Good", "Good"), "radish": ("Good", "Good", "Good"), "fenugreek": ("Good", "Good", "Good"),
             "coriander": ("Good", "Poor", "Good"), "amaranth": ("Good", "Poor", "Good"),
             "green gram": ("Good", "Fair", "Good"), "sunflower": ("Good", "Avoid", "Good"), "pea": ("Good", "Avoid", "Good")}
    compat_rows = [{"Seed": s, "Substrate": sub, "Suitability": v}
                   for s, vals in seeds.items() for sub, v in zip(("cocopeat", "tissue paper", "compost"), vals, strict=True)]
    compat = Table(
        "SeedCompatibility", [("Seed", T), ("Substrate", T), ("Suitability", T)], compat_rows,
        measures=[
            ("Suitability Rating", "SELECTEDVALUE(SeedCompatibility[Suitability])", None),
            ("Suitability Color", """SWITCH(
    SELECTEDVALUE(SeedCompatibility[Suitability]),
    "Good", "#2E9E6B",
    "Fair", "#B8A23A",
    "Poor", "#C77D2E",
    "Avoid", "#B5483D",
    "#10382C"
)""", None),
        ])
    env = Table(
        "EnvThresholds", [("Parameter", T), ("Good", T), ("Warning", T), ("Critical", T), ("Sort", INT)],
        [{"Parameter": "Temperature (lowland)", "Good": "22-28 °C", "Warning": "28-31 °C", "Critical": ">32 °C", "Sort": 1},
         {"Parameter": "Temperature (hill country)", "Good": "18-25 °C", "Warning": "25-28 °C", "Critical": ">30 °C", "Sort": 2},
         {"Parameter": "Humidity, growth phase", "Good": "50-70%", "Warning": "70-80%", "Critical": ">80% for 4+ h", "Sort": 3},
         {"Parameter": "Light", "Good": "8,000-15,000 lux, 12-14 h/day", "Warning": "<4,000 lux", "Critical": "Schedule missed", "Sort": 4}],
        sort={"Parameter": "Sort"})
    return [sensor, irrigation, outputs, faults, hardware, batches, trays, thresholds, dates, stages, substrates,
            profile, compat, env]


RELATIONSHIPS = [
    ("SensorData.tray_id", "Trays.tray_id"), ("IrrigationLogs.tray_id", "Trays.tray_id"),
    ("ModelOutputs.tray_id", "Trays.tray_id"), ("FaultEvents.tray_id", "Trays.tray_id"),
    ("CropBatches.tray_id", "Trays.tray_id"),
    ("SensorData.Date", "Dates.Date"), ("IrrigationLogs.Date", "Dates.Date"), ("ModelOutputs.Date", "Dates.Date"),
    ("FaultEvents.Date", "Dates.Date"), ("HardwareStatus.Date", "Dates.Date"),
    ("IrrigationLogs.growth_stage", "GrowthStages.stage_key"), ("ModelOutputs.growth_stage", "GrowthStages.stage_key"),
    ("Trays.media_type", "Substrates.Substrate"), ("SubstrateProfile.Substrate", "Substrates.Substrate"),
]


def write_model(tables: list[Table]) -> None:
    clean(MODEL / "definition")
    (MODEL / "diagramLayout.json").unlink(missing_ok=True)
    write_json(MODEL / "definition.pbism", {"version": "4.0", "settings": {}})
    write(MODEL / "definition" / "database.tmdl", "database SmartGrow\n\tcompatibilityLevel: 1567\n")
    refs = "\n".join(f"ref table {t.name}" for t in tables)
    write(MODEL / "definition" / "model.tmdl",
          "model Model\n\tculture: en-US\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n\tsourceQueryCulture: en-US\n"
          "\tannotation __PBI_TimeIntelligenceEnabled = 0\n\n" + refs + "\n")
    for t in tables:
        write(MODEL / "definition" / "tables" / f"{t.name}.tmdl", t.tmdl())
    write(MODEL / "definition" / "relationships.tmdl", "\n".join(
        f"relationship {guid()}\n\tfromColumn: {a}\n\ttoColumn: {b}\n" for a, b in RELATIONSHIPS))
    ignore = MODEL / ".gitignore"
    if not ignore.exists():
        write(ignore, ".pbi/\n")


# ---------------------------------------------------------------------------------------------------------------- report
def lit(value: str) -> dict:
    return {"expr": {"Literal": {"Value": value}}}


def s(value: str) -> dict:
    return lit(f"'{value}'")


def solid(color: str) -> dict:
    return {"solid": {"color": s(color)}}


def col(entity: str, prop: str) -> dict:
    return {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def mea(entity: str, prop: str) -> dict:
    return {"Measure": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def proj(field: dict, name: str | None = None, active: bool = False) -> dict:
    kind = "Measure" if "Measure" in field else "Column"
    ref = field[kind]
    entity, prop = ref["Expression"]["SourceRef"]["Entity"], ref["Property"]
    item = {"field": field, "queryRef": f"{entity}.{prop}", "nativeQueryRef": name or prop}
    if active:
        item["active"] = True
    return item


def container(title: str | None = None, bg: str = CARD_BG, border: str = CARD_BORDER) -> dict:
    out = {
        "background": [{"properties": {"show": lit("true"), "color": solid(bg), "transparency": lit("0D")}}],
        "border": [{"properties": {"show": lit("true"), "color": solid(border), "radius": lit("10D")}}],
    }
    if title:
        out["title"] = [{"properties": {"show": lit("true"), "text": s(title), "fontColor": solid(TEXT), "fontSize": lit("11D"),
                                         "alignment": s("left")}}]
    else:
        out["title"] = [{"properties": {"show": lit("false")}}]
    return out


class Page:
    def __init__(self, pid: str, name: str):
        self.pid, self.name, self.visuals, self.z = pid, name, [], 0

    def add(self, name: str, vtype: str, x: int, y: int, w: int, h: int, query=None, objects=None, vco=None, sort=None,
            sync: str | None = None) -> None:
        self.z += 1
        visual: dict = {"visualType": vtype, "drillFilterOtherVisuals": True}
        if query:
            visual["query"] = {"queryState": query}
            if sort:
                visual["query"]["sortDefinition"] = {"sort": sort, "isDefaultSort": False}
        if objects:
            visual["objects"] = objects
        if vco is not None:
            visual["visualContainerObjects"] = vco
        if sync:
            visual["syncGroup"] = {"groupName": sync, "fieldChanges": True, "filterChanges": True}
        self.visuals.append({
            "$schema": f"{SCH}/visualContainer/1.0.0/schema.json", "name": name,
            "position": {"x": x, "y": y, "z": self.z, "width": w, "height": h, "tabOrder": self.z},
            "visual": visual})


def header(page: Page, pages: list[Page]) -> None:
    page.add("title", "textbox", 16, 8, 320, 44, objects={"general": [{"properties": {"paragraphs": [
        {"textRuns": [{"value": "SmartGrow AI", "textStyle": {"fontWeight": "bold", "fontSize": "20pt", "color": TEXT}},
                      {"value": "  irrigation loop", "textStyle": {"fontSize": "11pt", "color": MUTED}}]}]}}]},
        vco={"background": [{"properties": {"show": lit("false")}}], "border": [{"properties": {"show": lit("false")}}],
             "title": [{"properties": {"show": lit("false")}}]})
    def state(prop, default, selected):
        return [{"properties": {prop: solid(default)}, "selector": {"id": "default"}},
                {"properties": {prop: solid(selected)}, "selector": {"id": "selected"}}]

    page.add("nav", "pageNavigator", 340, 10, 720, 40, objects={
        "fill": state("fillColor", CARD_BG, LIME), "text": state("fontColor", TEXT, PAGE_BG),
        "outline": [{"properties": {"lineColor": solid(CARD_BORDER)}, "selector": {"id": "default"}}],
    }, vco={
        "background": [{"properties": {"show": lit("false")}}], "title": [{"properties": {"show": lit("false")}}]})
    page.add("note", "textbox", 1070, 14, 194, 34, objects={"general": [{"properties": {"paragraphs": [
        {"textRuns": [{"value": "Sample data - 7 days", "textStyle": {"fontSize": "10pt", "color": AMBER}}]}]}}]},
        vco={"background": [{"properties": {"show": lit("false")}}], "border": [{"properties": {"show": lit("false")}}],
             "title": [{"properties": {"show": lit("false")}}]})


def slicer(page: Page, name: str, field: dict, x: int, w: int, title: str, sync: str, mode: str = "Dropdown") -> None:
    page.add(name, "slicer", x, 58, w, 52, query={"Values": {"projections": [proj(field, active=True)]}},
             objects={"data": [{"properties": {"mode": s(mode)}}],
                      "header": [{"properties": {"show": lit("false")}}]},
             vco=container(title), sync=sync)


def card(page: Page, name: str, measure_field: dict, x: int, w: int, title: str, y: int = 118, h: int = 92,
         accent: bool = False) -> None:
    page.add(name, "card", x, y, w, h, query={"Values": {"projections": [proj(measure_field)]}},
             objects={"labels": [{"properties": {"color": solid(LIME if accent else TEXT), "fontSize": lit("26D")}}],
                      "categoryLabels": [{"properties": {"show": lit("false")}}]},
             vco=container(title))


def kpis(page: Page, items: list[tuple[str, dict]], y: int = 118) -> None:
    width, gap = 198, 12
    for i, (title, field) in enumerate(items):
        card(page, f"kpi{i}", field, 16 + i * (width + gap), width, title, y=y, accent=i == 0)


def chart(page: Page, name: str, vtype: str, x, y, w, h, title, category=None, series=None, values=(), sort=None) -> None:
    query: dict = {}
    if category is not None:
        query["Category"] = {"projections": [proj(category, active=True)]}
    if series is not None:
        query["Series"] = {"projections": [proj(series, active=True)]}
    query["Y"] = {"projections": [proj(v) for v in values]}
    page.add(name, vtype, x, y, w, h, query=query, vco=container(title), sort=sort)


def table_style() -> dict:
    return {
        "columnHeaders": [{"properties": {"fontColor": solid(LIME), "backColor": solid("#0D2E24"), "fontSize": lit("10D")}}],
        "values": [{"properties": {"fontColorPrimary": solid(TEXT), "backColorPrimary": solid(CARD_BG),
                                    "fontColorSecondary": solid(TEXT), "backColorSecondary": solid("#12402F"),
                                    "fontSize": lit("10D")}}],
        "grid": [{"properties": {"gridHorizontalColor": solid(CARD_BORDER), "outlineColor": solid(CARD_BORDER)}}],
    }


def table(page: Page, name: str, x, y, w, h, title, fields, sort=None) -> None:
    page.add(name, "tableEx", x, y, w, h, query={"Values": {"projections": [proj(f) for f in fields]}},
             objects=table_style(), vco=container(title), sort=sort)


def matrix(page: Page, name: str, x, y, w, h, title, rows, columns, values, objects=None) -> None:
    page.add(name, "pivotTable", x, y, w, h, query={
        "Rows": {"projections": [proj(rows, active=True)]}, "Columns": {"projections": [proj(columns, active=True)]},
        "Values": {"projections": [proj(values)]}},
        objects={**table_style(),
                 "rowHeaders": [{"properties": {"fontColor": solid(TEXT), "backColor": solid(CARD_BG)}}],
                 "rowTotal": [{"properties": {"show": lit("false")}}], "columnTotal": [{"properties": {"show": lit("false")}}],
                 "subTotals": [{"properties": {"rowSubtotals": lit("false"), "columnSubtotals": lit("false")}}],
                 **(objects or {})}, vco=container(title))


def build_pages() -> list[Page]:
    date_f, tray_f = col("Dates", "Date"), col("Trays", "tray_id")
    pages = [Page("p1_overview", "Overview"), Page("p2_environment", "Moisture & Environment"),
             Page("p3_loop", "Irrigation Loop"), Page("p4_faults", "Faults"), Page("p5_hardware", "Hardware & Crop")]
    for p in pages:
        header(p, pages)
        slicer(p, "s_date", date_f, 16, 300, "Date range", "sync_date", mode="Between")
    p1, p2, p3, p4, p5 = pages

    # ----- Overview -------------------------------------------------------------------------------------------------------
    slicer(p1, "s_tray", tray_f, 324, 150, "Tray", "sync_tray")
    slicer(p1, "s_seed", col("Trays", "seed_type"), 482, 170, "Seed type", "sync_seed")
    slicer(p1, "s_media", col("Substrates", "Substrate"), 660, 170, "Substrate", "sync_media")
    slicer(p1, "s_stage", col("GrowthStages", "Stage"), 838, 180, "Growth stage", "sync_stage")
    kpis(p1, [("Avg soil moisture", mea("SensorData", "Avg Moisture")), ("Time in optimal band", mea("SensorData", "Time In Band %")),
              ("Irrigation events", mea("IrrigationLogs", "Irrigation Events")), ("Water used", mea("IrrigationLogs", "Total Water (mL)")),
              ("Active faults", mea("FaultEvents", "Active Faults")), ("Water response score", mea("ModelOutputs", "Avg Water Response Score"))])
    chart(p1, "c_band", "lineChart", 16, 218, 620, 250, "Soil moisture vs optimal band (% VWC)", col("SensorData", "timestamp"),
          values=[mea("SensorData", "Avg Moisture"), mea("Trays", "Optimal Min"), mea("Trays", "Optimal Max")])
    chart(p1, "c_water_day", "columnChart", 648, 218, 330, 250, "Water used by day and tray (mL)", col("Dates", "Day Label"),
          series=tray_f, values=[mea("IrrigationLogs", "Total Water (mL)")])
    chart(p1, "c_decisions", "donutChart", 990, 218, 274, 250, "Policy decisions", col("ModelOutputs", "Decision"),
          values=[mea("ModelOutputs", "Policy Decisions")])
    table(p1, "t_trays", 16, 476, 620, 236, "Tray summary", [
        tray_f, col("Trays", "seed_type"), col("Trays", "media_type"), mea("SensorData", "Avg Moisture"),
        mea("SensorData", "Time In Band %"), mea("IrrigationLogs", "Irrigation Events"), mea("IrrigationLogs", "Total Water (mL)"),
        mea("FaultEvents", "Active Faults")])
    chart(p1, "c_hour", "columnChart", 648, 476, 616, 236, "Irrigations by time of day", col("IrrigationLogs", "Hour"),
          series=col("IrrigationLogs", "Trigger"), values=[mea("IrrigationLogs", "Irrigation Events")])

    # ----- Moisture & environment ---------------------------------------------------------------------------------------------
    slicer(p2, "s_tray", tray_f, 324, 150, "Tray", "sync_tray")
    slicer(p2, "s_seed", col("Trays", "seed_type"), 482, 170, "Seed type", "sync_seed")
    slicer(p2, "s_media", col("Substrates", "Substrate"), 660, 170, "Substrate", "sync_media")
    kpis(p2, [("Avg soil moisture", mea("SensorData", "Avg Moisture")), ("Latest moisture", mea("SensorData", "Latest Moisture")),
              ("Time in optimal band", mea("SensorData", "Time In Band %")), ("Avg temperature", mea("SensorData", "Avg Temperature")),
              ("Avg humidity", mea("SensorData", "Avg Humidity")), ("Avg light", mea("SensorData", "Avg Light"))])
    chart(p2, "c_moist_tray", "lineChart", 16, 218, 760, 250, "Soil moisture by tray (% VWC)", col("SensorData", "timestamp"),
          series=tray_f, values=[mea("SensorData", "Avg Moisture")])
    matrix(p2, "m_profile", 788, 218, 476, 250, "Optimal conditions by substrate", col("SubstrateProfile", "Setting"),
           col("SubstrateProfile", "Substrate"), mea("SubstrateProfile", "Optimal Value"))
    chart(p2, "c_temp", "lineChart", 16, 476, 300, 236, "Temperature (°C)", col("SensorData", "timestamp"),
          values=[mea("SensorData", "Avg Temperature")])
    chart(p2, "c_hum", "lineChart", 328, 476, 300, 236, "Humidity (% RH)", col("SensorData", "timestamp"),
          values=[mea("SensorData", "Avg Humidity")])
    chart(p2, "c_light", "areaChart", 640, 476, 300, 236, "Light (lux)", col("SensorData", "timestamp"),
          values=[mea("SensorData", "Avg Light")])
    chart(p2, "c_level", "lineChart", 952, 476, 312, 236, "Reservoir level (%)", col("SensorData", "timestamp"),
          values=[mea("SensorData", "Avg Water Level")])

    # ----- Irrigation loop (Models 1-3) -------------------------------------------------------------------------------------------
    slicer(p3, "s_tray", tray_f, 324, 150, "Tray", "sync_tray")
    slicer(p3, "s_stage", col("GrowthStages", "Stage"), 482, 180, "Growth stage", "sync_stage")
    slicer(p3, "s_trigger", col("IrrigationLogs", "Trigger"), 670, 160, "Trigger", "sync_trigger")
    slicer(p3, "s_version", col("ModelOutputs", "model_version"), 838, 200, "Model version", "sync_version")
    kpis(p3, [("Irrigation events", mea("IrrigationLogs", "Irrigation Events")), ("Water used", mea("IrrigationLogs", "Total Water (mL)")),
              ("Avg expected response", mea("IrrigationLogs", "Avg Expected Response")),
              ("Avg actual response", mea("IrrigationLogs", "Avg Actual Response")),
              ("Avg deviation", mea("IrrigationLogs", "Avg Response Deviation")),
              ("Water response score", mea("ModelOutputs", "Avg Water Response Score"))])
    chart(p3, "c_exp_act", "clusteredColumnChart", 16, 218, 400, 250, "Expected vs actual response by tray (% points)", tray_f,
          values=[mea("IrrigationLogs", "Avg Expected Response"), mea("IrrigationLogs", "Avg Actual Response")])
    chart(p3, "c_dev", "areaChart", 428, 218, 420, 250, "Response deviation over time (% points)", col("IrrigationLogs", "timestamp"),
          values=[mea("IrrigationLogs", "Avg Response Deviation")])
    chart(p3, "c_version", "clusteredColumnChart", 860, 218, 404, 250, "Water response score by model version", col("ModelOutputs", "model_version"),
          values=[mea("ModelOutputs", "Avg Water Response Score")])
    table(p3, "t_events", 16, 476, 1248, 236, "Irrigation events", [
        col("IrrigationLogs", "timestamp"), tray_f, col("GrowthStages", "Stage"), col("IrrigationLogs", "Trigger"),
        col("IrrigationLogs", "water_volume"), col("IrrigationLogs", "pre_irrigation_moisture"),
        col("IrrigationLogs", "post_irrigation_moisture"), col("IrrigationLogs", "expected_response"),
        col("IrrigationLogs", "actual_response"), col("IrrigationLogs", "response_deviation"),
        col("IrrigationLogs", "avg_flow_rate"), col("IrrigationLogs", "flow_cv")],
        sort=[{"field": col("IrrigationLogs", "timestamp"), "direction": "Descending"}])

    # ----- Faults -----------------------------------------------------------------------------------------------------------------------
    slicer(p4, "s_tray", tray_f, 324, 150, "Tray", "sync_tray")
    slicer(p4, "s_hyp", col("FaultEvents", "Hypothesis"), 482, 220, "Hypothesis", "sync_hyp")
    slicer(p4, "s_sev", col("FaultEvents", "Severity Label"), 710, 150, "Severity", "sync_sev")
    slicer(p4, "s_status", col("FaultEvents", "Status"), 868, 150, "Status", "sync_status")
    kpis(p4, [("Faults detected", mea("FaultEvents", "Total Faults")), ("Active faults", mea("FaultEvents", "Active Faults")),
              ("Critical faults", mea("FaultEvents", "Critical Faults")), ("Resolved", mea("FaultEvents", "Resolved %")),
              ("Avg time to resolve", mea("FaultEvents", "Avg Hours To Resolve")),
              ("Avg fault confidence", mea("FaultEvents", "Avg Fault Confidence"))])
    chart(p4, "c_hyp", "donutChart", 16, 218, 310, 250, "Faults by likely cause", col("FaultEvents", "Hypothesis"),
          values=[mea("FaultEvents", "Total Faults")])
    chart(p4, "c_status", "donutChart", 338, 218, 260, 250, "Status", col("FaultEvents", "Status"),
          values=[mea("FaultEvents", "Total Faults")])
    chart(p4, "c_fday", "columnChart", 610, 218, 340, 250, "Faults by day and severity", col("Dates", "Day Label"),
          series=col("FaultEvents", "Severity Label"), values=[mea("FaultEvents", "Total Faults")])
    chart(p4, "c_ftray", "barChart", 962, 218, 302, 250, "Faults by tray", tray_f, values=[mea("FaultEvents", "Total Faults")])
    table(p4, "t_faults", 16, 476, 1248, 236, "Fault log", [
        col("FaultEvents", "timestamp"), tray_f, col("FaultEvents", "Hypothesis"), col("FaultEvents", "Severity Label"),
        col("FaultEvents", "Status"), col("FaultEvents", "fault_confidence"), col("FaultEvents", "flow_class"),
        col("FaultEvents", "response_class"), col("FaultEvents", "diagnostic_action"), col("FaultEvents", "recovery_action"),
        col("FaultEvents", "resolved_at")],
        sort=[{"field": col("FaultEvents", "timestamp"), "direction": "Descending"}])

    # ----- Hardware & crop ------------------------------------------------------------------------------------------------------------------
    slicer(p5, "s_esp", col("HardwareStatus", "esp32_id"), 324, 170, "Controller", "sync_esp")
    slicer(p5, "s_overall", col("HardwareStatus", "Overall Status"), 502, 170, "System status", "sync_overall")
    kpis(p5, [("System healthy", mea("HardwareStatus", "Healthy %")), ("Hardware snapshots", mea("HardwareStatus", "Snapshots")),
              ("Active batches", mea("CropBatches", "Active Batches")), ("Active faults", mea("FaultEvents", "Active Faults")),
              ("Avg reservoir level", mea("SensorData", "Avg Water Level")), ("Water used", mea("IrrigationLogs", "Total Water (mL)"))])
    table(p5, "t_hw", 16, 218, 760, 250, "Hardware status log", [
        col("HardwareStatus", "timestamp"), col("HardwareStatus", "Overall Status"), col("HardwareStatus", "solenoid_1_status"),
        col("HardwareStatus", "solenoid_2_status"), col("HardwareStatus", "solenoid_3_status"), col("HardwareStatus", "fan_status"),
        col("HardwareStatus", "water_pump_status"), col("HardwareStatus", "power_status"), col("HardwareStatus", "connectivity_status")],
        sort=[{"field": col("HardwareStatus", "timestamp"), "direction": "Descending"}])
    chart(p5, "c_hw_day", "columnChart", 788, 218, 476, 250, "Hardware snapshots by day and status", col("Dates", "Day Label"),
          series=col("HardwareStatus", "Overall Status"), values=[mea("HardwareStatus", "Snapshots")])
    table(p5, "t_batches", 16, 476, 620, 236, "Crop batches", [
        tray_f, col("CropBatches", "seed_type"), col("CropBatches", "media_type"), col("CropBatches", "planting_date"),
        col("CropBatches", "expected_harvest_date"), mea("CropBatches", "Days After Sowing"), col("CropBatches", "batch_status")])
    matrix(p5, "m_compat", 648, 476, 616, 236, "Seed and substrate compatibility", col("SeedCompatibility", "Seed"),
           col("SeedCompatibility", "Substrate"), mea("SeedCompatibility", "Suitability Rating"),
           objects={"values": [{"properties": {"backColor": {"solid": {"color": {"expr": {"Measure": {
               "Expression": {"SourceRef": {"Entity": "SeedCompatibility"}}, "Property": "Suitability Color"}}}}},
               "fontColor": solid("#FFFFFF")},
               "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}], "metadata": "SeedCompatibility.Suitability Rating"}}]})
    return pages


def theme() -> dict:
    return {
        "name": "SmartGrow Dark Green",
        "dataColors": DATA_COLORS,
        "background": CARD_BG, "foreground": TEXT, "tableAccent": GREEN,
        "good": GREEN, "neutral": AMBER, "bad": RED, "maximum": LIME, "center": GREEN, "minimum": DEEP,
        "textClasses": {
            "label": {"fontFace": "Segoe UI", "fontSize": 10, "color": TEXT},
            "title": {"fontFace": "Segoe UI Semibold", "fontSize": 12, "color": TEXT},
        },
        "visualStyles": {
            "*": {"*": {
                "categoryAxis": [{"labelColor": {"solid": {"color": MUTED}}}],
                "valueAxis": [{"labelColor": {"solid": {"color": MUTED}}, "gridlineColor": {"solid": {"color": "#1A4A39"}}}],
                "legend": [{"labelColor": {"solid": {"color": TEXT}}}],
            }},
        },
    }


def write_report(pages: list[Page], active: str | None = None) -> None:
    clean(REPORT / "definition")
    clean(REPORT / "StaticResources")
    write_json(REPORT / "definition.pbir", {"version": "4.0", "datasetReference": {"byPath": {"path": "../SmartGrow.SemanticModel"}}})
    d = REPORT / "definition"
    write_json(d / "version.json", {"$schema": f"{SCH}/versionMetadata/1.0.0/schema.json", "version": "2.0.0"})
    t = theme()
    write_json(REPORT / "StaticResources" / "RegisteredResources" / "SmartGrowTheme.json", t)
    write_json(ROOT / "powerbi_theme.json", t)
    write_json(d / "report.json", {
        "$schema": f"{SCH}/report/3.3.0/schema.json",
        "themeCollection": {"customTheme": {"name": "SmartGrowTheme.json", "type": "RegisteredResources",
                                            "reportVersionAtImport": {"visual": "1.8.91", "report": "2.0.91", "page": "1.3.91"}}},
        "resourcePackages": [{"name": "RegisteredResources", "type": "RegisteredResources",
                              "items": [{"name": "SmartGrowTheme.json", "path": "SmartGrowTheme.json", "type": "CustomTheme"}]}],
        "settings": {"useEnhancedTooltips": False},
    })
    for page in pages:
        pdir = d / "pages" / page.pid
        write_json(pdir / "page.json", {
            "$schema": f"{SCH}/page/2.1.0/schema.json", "name": page.pid, "displayName": page.name,
            "displayOption": "FitToPage", "height": 720, "width": 1280,
            "objects": {"background": [{"properties": {"color": solid(PAGE_BG), "transparency": lit("0D")}}],
                        "outspace": [{"properties": {"color": solid(PAGE_BG)}}]}})
        for visual in page.visuals:
            write_json(pdir / "visuals" / visual["name"] / "visual.json", visual)
    write_json(d / "pages" / "pages.json", {
        "$schema": f"{SCH}/pagesMetadata/1.0.0/schema.json", "pageOrder": [p.pid for p in pages],
        "activePageName": active or pages[0].pid})
    ignore = REPORT / ".gitignore"
    if not ignore.exists():
        write(ignore, ".pbi/\n")


def main() -> None:
    active = sys.argv[1] if len(sys.argv) > 1 else None  # e.g. p3_loop, to open on a given page while developing
    data = build_demo_dataset()
    tables = build_tables(data)
    write_model(tables)
    write_report(build_pages(), active)
    write(ROOT / "SmartGrow.pbip", json.dumps(
        {"version": "1.0", "artifacts": [{"report": {"path": "SmartGrow.Report"}}], "settings": {"enableAutoRecovery": True}},
        indent=2) + "\n")
    print(f"Wrote {len(tables)} tables and the report to {ROOT}")


if __name__ == "__main__":
    main()
