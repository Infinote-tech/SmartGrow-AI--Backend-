// SmartGrow AI -- reading LIVE data from MongoDB in the Power BI project (scripts/SmartGrow.pbip).
//
// The shipped project embeds the demo dataset, so it works with no setup. To use your own database instead,
// open Transform data and, for each fact table (SensorData, IrrigationLogs, ModelOutputs, FaultEvents,
// HardwareStatus, CropBatches), replace the first step ("Source = #table(...)") with the query below, changing only
// CollectionName. The later steps (Date, Hour, labels, ...) stay as they are.
//
// Requirements: Python installed and configured in Power BI (File > Options > Python scripting) with
//   pip install pandas pymongo
// Power BI has no built-in MongoDB connector, so Python is the simplest route. Datetimes are returned as UTC.
//
// Optional: python scripts/seed_demo_data.py loads the same demo rows into MongoDB (and --clear removes them).

let
    MongoUri       = "mongodb://localhost:27017",   // <- MONGO_URI from .env
    DbName         = "smartgrow_db",                // <- MONGO_DB_NAME from .env
    CollectionName = "sensor_data",                 // <- sensor_data | irrigation_logs | model_outputs | fault_events
                                                    //    hardware_status | crop_batches | thresholds
    PyScript = Text.Combine({
        "import pandas as pd",
        "from pymongo import MongoClient",
        "docs = list(MongoClient('" & MongoUri & "')['" & DbName & "']['" & CollectionName & "'].find({}, {'_id': 0}))",
        "frame = pd.DataFrame(docs)",
        "for column in frame.columns:",
        "    if frame[column].map(lambda v: isinstance(v, (dict, list))).any():",
        "        frame[column] = frame[column].astype(str)"
    }, "#(lf)"),
    Python = Python.Execute(PyScript),
    Source = Python{[Name = "frame"]}[Value]
in
    Source

// Notes
//  * Column names equal the API field names, so the model's measures keep working.
//  * Mongo returns missing optional fields as nulls; make sure each column keeps its type
//    (Transform data > Detect data type, or keep the typed columns from the original query).
//  * The `Trays` table (tray -> seed, media, optimal_min, optimal_max) is a dashboard dimension that is not an API
//    collection: keep its embedded rows, or maintain a `trays` collection with those fields.
