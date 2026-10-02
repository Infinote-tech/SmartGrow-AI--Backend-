// SmartGrow AI -- Power Query (M) queries for the Power BI dashboard.
// In Power BI Desktop: Home > Get data > Blank query > Advanced Editor. Paste ONE query (the part under each
// "=====" heading) per blank query and rename the query to the name in the heading.
// TrayEntries needs Python with `pip install pandas pymongo`; otherwise export a CSV with
// `python scripts/seed_tray_entries.py --export-csv tray_entries.csv` and use the TrayEntriesCsv variant.

// ===== TrayEntries =====
let
    MongoUri = "mongodb://localhost:27017",   // <- your MONGO_URI from .env
    DbName   = "smartgrow_db",                // <- your MONGO_DB_NAME
    PyScript = Text.Combine({
        "import pandas as pd",
        "from pymongo import MongoClient",
        "db = MongoClient('" & MongoUri & "')['" & DbName & "']",
        "users = {str(u['_id']): u.get('full_name', '') for u in db.users.find()}",
        "rows = [{'id': str(d['_id']), 'user_id': d['user_id'], 'user_name': users.get(d['user_id'], ''), 'seed_type': d['seed_type'], 'substrate_type': d['substrate_type'], 'tray_number': d['tray_number'], 'date': d['date'], 'time': d['time']} for d in db.tray_entries.find()]",
        "tray_entries = pd.DataFrame(rows, columns=['id','user_id','user_name','seed_type','substrate_type','tray_number','date','time'])"
    }, "#(lf)"),
    Source   = Python.Execute(PyScript),
    Raw      = Source{[Name = "tray_entries"]}[Value],
    Typed    = Table.TransformColumnTypes(Raw, {{"tray_number", Int64.Type}, {"seed_type", type text}, {"substrate_type", type text}}),
    WithDate = Table.AddColumn(Typed, "Entry Date", each Date.FromText([date]), type date),
    WithHour = Table.AddColumn(WithDate, "Hour", each Number.FromText(Text.Start([time], 2)), Int64.Type),
    WithDay  = Table.AddColumn(WithHour, "Day of Week", each Date.DayOfWeekName([Entry Date]), type text),
    WithDayN = Table.AddColumn(WithDay, "Day Number", each Date.DayOfWeek([Entry Date], Day.Monday), Int64.Type),
    WithPart = Table.AddColumn(WithDayN, "Time of Day", each if [Hour] < 12 then "Morning" else if [Hour] < 17 then "Afternoon" else "Evening", type text),
    Result   = Table.RemoveColumns(WithPart, {"date"})
in
    Result

// ===== TrayEntriesCsv (use instead of TrayEntries if you don't want Python) =====
// Replace Source/Raw above with the two lines below, keep every step from `Typed` onward, and name the query TrayEntries.
//   Source = Csv.Document(File.Contents("C:\path\to\tray_entries.csv"), [Delimiter = ",", Encoding = 65001]),
//   Raw    = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
// (the CSV has no user_name column -- drop that from the DataFrame columns if you rely on it)

// ===== SubstrateProfile =====
// Optimal conditions per substrate (relative moisture %, calibrate each sensor first).
let
    Source = #table(
        type table [Substrate = text, Setting = text, Value = text, Sort = Int64.Type],
        {
            {"cocopeat", "Dry (irrigate)", "<45%", 1}, {"tissue paper", "Dry (irrigate)", "<50%", 1}, {"compost", "Dry (irrigate)", "<40%", 1},
            {"cocopeat", "Target after watering", "~65%", 2}, {"tissue paper", "Target after watering", "~70%", 2}, {"compost", "Target after watering", "~60%", 2},
            {"cocopeat", "Good band", "55-75%", 3}, {"tissue paper", "Good band", "60-80%", 3}, {"compost", "Good band", "50-70%", 3},
            {"cocopeat", "Too wet", ">85%", 4}, {"tissue paper", "Too wet", ">90%", 4}, {"compost", "Too wet", ">80%", 4},
            {"cocopeat", "Dose size", "Medium", 5}, {"tissue paper", "Dose size", "Small", 5}, {"compost", "Dose size", "Medium-small", 5},
            {"cocopeat", "Min interval between doses", "2 h", 6}, {"tissue paper", "Min interval between doses", "45 min", 6}, {"compost", "Min interval between doses", "3 h", 6},
            {"cocopeat", "Max pump run per dose", "10 s", 7}, {"tissue paper", "Max pump run per dose", "4 s", 7}, {"compost", "Max pump run per dose", "8 s", 7},
            {"cocopeat", "Moisture check interval", "5 min", 8}, {"tissue paper", "Moisture check interval", "2 min", 8}, {"compost", "Moisture check interval", "5 min", 8}
        })
in
    Source

// ===== SeedCompatibility =====
let
    Source = #table(
        type table [Seed = text, Substrate = text, Suitability = text],
        {
            {"mustard", "cocopeat", "Good"}, {"mustard", "tissue paper", "Good"}, {"mustard", "compost", "Good"},
            {"radish", "cocopeat", "Good"}, {"radish", "tissue paper", "Good"}, {"radish", "compost", "Good"},
            {"fenugreek", "cocopeat", "Good"}, {"fenugreek", "tissue paper", "Good"}, {"fenugreek", "compost", "Good"},
            {"coriander", "cocopeat", "Good"}, {"coriander", "tissue paper", "Poor"}, {"coriander", "compost", "Good"},
            {"amaranth", "cocopeat", "Good"}, {"amaranth", "tissue paper", "Poor"}, {"amaranth", "compost", "Good"},
            {"green gram", "cocopeat", "Good"}, {"green gram", "tissue paper", "Fair"}, {"green gram", "compost", "Good"},
            {"sunflower", "cocopeat", "Good"}, {"sunflower", "tissue paper", "Avoid"}, {"sunflower", "compost", "Good"},
            {"pea", "cocopeat", "Good"}, {"pea", "tissue paper", "Avoid"}, {"pea", "compost", "Good"}
        })
in
    Source

// ===== EnvThresholds =====
let
    Source = #table(
        type table [Parameter = text, Good = text, Warning = text, Critical = text],
        {
            {"Temperature (lowland)", "22-28 °C", "28-31 °C", ">32 °C"},
            {"Temperature (hill country)", "18-25 °C", "25-28 °C", ">30 °C"},
            {"Humidity, growth phase", "50-70%", "70-80%", ">80% for 4+ h"},
            {"Light", "8,000-15,000 lux, 12-14 h/day", "<4,000 lux", "Schedule missed"}
        })
in
    Source
