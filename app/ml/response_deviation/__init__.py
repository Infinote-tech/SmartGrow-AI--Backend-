"""
Model 2 -- Response-Deviation / Fault.

Stage A compares the measured moisture response with Model 1's expectation (normalised by its interval).
Stage B explains an anomalous deviation from the flow pattern and the response class, using versioned
rules (`rules-v0`). A learned classifier (trained on deliberately injected faults) is preferred when present.
"""
