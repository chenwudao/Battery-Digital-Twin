# Video script

Synthetic narration: `en-US-AndrewNeural`, rate `+3%`. The final video is 1080p with burned-in English captions and a separate SRT.

## 00:00 — Title and problem

Battery packs are everywhere: scooters, robots, and small storage systems. But the states that matter are hidden. The operator sees voltage, current, and surface temperature, not the state of charge, the internal resistance, or the core temperature. Failures are often handled after they happen. This project builds a digital twin for a 48 volt, thirteen cell pack, about ten amp hours. The user is a fleet or storage operator who needs three answers: how much runtime is left, is the pack getting less healthy, and will the planned load overheat it? The twin estimates hidden states from measurements, predicts remaining runtime, explains anomalies, and supports what-if decisions. We built all five components: acquisition, MQTT communication, data management, a hybrid model, and a user service. Every claim is backed by an executable check or a measured number.

## 00:54 — Hidden states and user decisions

So the project is built around hidden states. On the left are the measurements: voltage, current, and surface temperature. In the middle are the three questions that operators actually ask: how much runtime is left, is the pack degrading, and will a planned load overheat it? On the right is what the twin adds. An extended Kalman filter fuses measurements; residuals detect and explain faults; and forward simulation answers what-if scenarios. This is the value of a digital twin: it turns raw signals into an actionable estimate.

## 01:27 — Architecture and truth separation

The architecture has five moving parts. On the left, the plant simulator represents the real world. It uses a two-RC electrical model, a two-node thermal model, temperature-dependent resistance, aging drift, noise, and packet loss. It publishes telemetry at one hertz over MQTT. The same broker feeds the ingestor and the twin. The ingestor validates data and writes SQLite. The twin runs a deliberately different model: one RC, one thermal node, an extended Kalman filter, and online resistance tracking. It publishes state and alarms. The dashboard consumes live MQTT and historical SQLite data. The critical design choice is separation. Plant parameters are private, and truth is written only to a local CSV. The twin never subscribes to truth. That avoids validating a model against itself.

## 02:20 — Acquisition and assumptions

The acquisition table has five signals: pack voltage and current at one hertz, surface temperature at one hertz, ambient temperature at zero point one hertz, and a sequence plus source timestamp on every message. Current is positive on discharge. The simulator adds voltage, current, and temperature noise, quantization, and a small packet loss rate. It also supports a simulation speed multiplier, so a two-hour discharge can be demonstrated in six minutes. Source time is simulation time; ingest time is wall-clock time. The assumptions are explicit: cells are balanced, capacity is constant within a run, the OCV curve comes from literature, convection is fixed, and hysteresis is ignored. The plant uses private parameters; the twin only receives telemetry.

## 03:08 — MQTT contract

Communication uses MQTT only. There are separate topics for telemetry, metadata, status, twin state, twin alarms, load commands, fault injection, and what-if requests and responses. Telemetry and twin outputs use QoS one. Meta and status are retained, so a dashboard that connects late immediately knows the units and the asset state. Status also configures a last will: if the simulator dies, the broker publishes offline, retained. The ingestor uses a persistent session, so a normal disconnect does not drop QoS one messages. Commands are logged to SQLite. Field names carry units. In the demo you will see actual topic traffic and the resulting dashboard updates.

## 03:53 — Data management

Data management starts with a raw message table that keeps every JSON payload, topic, and arrival time. Then a narrow clean table stores asset, variable, value, unit, source time, ingest time, sequence, and quality. Every message is range checked; impossible values are marked invalid. A uniqueness constraint removes duplicates. Sequence gaps are recorded as gaps, not filled with zero. For offline analysis, a one-hertz alignment function keeps missing values as NaN. The database uses WAL and batched commits. Queries and CSV export are available from the dashboard and a small CLI. This separation keeps the twin auditable: raw data is never overwritten by cleaning.

## 04:38 — Model and identification

The plant and twin intentionally differ. The plant is a two-RC model. Its resistance follows an Arrhenius temperature law, and it has two thermal nodes, core and surface, plus aging drift. The twin is a one-RC model with a single thermal node. Its voltage is OCV of state of charge, minus current times R zero, minus the RC polarization. State of charge integrates current; the thermal node balances Joule heating against convection. The twin does not trust the initial state of charge. It starts at sixty percent while the plant starts at ninety-five. An extended Kalman filter estimates SoC, RC voltage, and surface temperature. A recursive least-squares tracker updates resistance, and a short-window regression separates a resistance change from a voltage-sensor offset. State of health is nominal resistance divided by estimated resistance. Offline, parameters are identified from HPPC data using least squares on measured voltage, current, and temperature only. The fit is eight point eight millivolts RMS.

## 05:43 — Evaluation T1–T3

Now the quantitative part. First, open-loop voltage accuracy on a drive cycle that was not used for identification. The one-RC twin has thirteen millivolts RMS error and forty-two millivolts maximum error. A no-relaxation baseline is two hundred eighty-six millivolts, so the RC branch matters. Second, state of charge. Starting deliberately wrong by thirty-five points, the filter converges within two percent in six seconds. After convergence, RMSE is zero point one one percent. A pure coulomb counter with the same wrong initial value stays at thirty-five percent error. Third, endurance. At ten checkpoints on a two-hour drive cycle, the twin predicts time to cutoff with four point two percent mean absolute percentage error. Linear voltage extrapolation has over one hundred percent error because load changes make the voltage slope misleading. These are the kinds of numbers that separate a model from a curve.

## 06:40 — Evaluation T4–T5

For anomaly detection, thresholds are fixed only from normal data. On one hour of normal operation there are zero false alarms. A fifty percent resistance step is detected in sixty-three seconds by the residual regression. A cooling failure under load is detected in three hundred fifty-two seconds, compared with one thousand one hundred fifty-eight seconds for a fixed temperature threshold. A half-volt voltage-sensor step is caught in one second by the acute residual check. For robustness, we add five percent packet loss and double the sensor noise. State-of-charge RMSE grows from zero point zero nine seven to zero point one zero eight percent. Voltage residual RMS doubles, as expected, and temperature accuracy is unchanged. This is not perfection, but it is measured degradation.

## 07:29 — Integrated demo setup

Now the live integration demo. The broker, ingestor, twin, simulator, and dashboard are started with one command. The dashboard is receiving the actual MQTT stream. We will change the load, inject a cooling fault, read the alarm, run a what-if scenario, and finally trigger the last will by killing the simulator.

## 07:49 — Live dashboard demo

### 07:49 — Live dashboard overview

This is the live dashboard. The green banner shows fresh MQTT data. The top row shows state of charge, state of health from resistance, estimated core temperature, and remaining runtime. The charts compare measured and twin-predicted voltage, temperature, SoC, and residuals. The twin is updating on every telemetry sample.

### 08:11 — Apply an 18 A load

I will apply a constant eighteen-amp load for the next hour. The dashboard publishes a load command to the simulator. The plant changes its current; new telemetry arrives at one hertz; and the twin recomputes SoC, power loss, temperature, and remaining runtime. This is the core digital-twin loop: new data changes the digital representation.

### 08:34 — Inject cooling failure

Now I inject a cooling failure while the pack is under load. The plant reduces its surface-to-ambient conductance to five percent. The measured temperature rises faster than the twin thermal model expects, so the pre-fit thermal residual grows. After the residual stays above the calibrated threshold, the detector raises a thermal anomaly.

### 08:57 — Alarm explanation and safe load

The alarm is not just a red light. It shows the thermal residual and the estimated resistance ratio, and it recommends reducing load and inspecting the cooling path. I follow the recommendation and reduce the load to five amps. Normal operation produced zero false alarms with the same thresholds.

### 09:16 — What-if decision

Next, a what-if decision. Twenty amps, thirty minutes, thirty-five degree ambient. The twin starts from the current SoC, resistance, and temperature, and simulates forward in time. It reports both the time to cutoff voltage and the time to the temperature limit, then recommends a safer current. The response comes back over MQTT.

### 09:38 — SQLite data layer

The data tab shows the raw and clean SQLite tables, the latest measurements, source versus ingest timestamps, and CSV export. Every command and what-if request is also logged for traceability.

### 09:52 — LWT offline / stale data

Finally, I kill the simulator. The broker publishes the retained last-will offline status. The dashboard first warns that data is stale, then turns red after the offline threshold. The twin and historical database remain available. This is the complete integration path.

## 10:14 — Conclusion

What does this project not claim? It is a simulation, not a real pack. Cells are treated as identical, so cell imbalance and local hot spots are out of scope. The one-RC model degrades at low state of charge and low temperature. The anomaly thresholds are calibrated on one normal duty cycle. Small sensor offsets are hard to separate from SoC changes, and SQLite is fine for one asset, not a fleet. Still, the twin closes the loop: measurements update hidden states, alarms explain themselves, and what-if requests use the same physics. The result is a working, reproducible course project with executable evidence. Thank you.


## Chapters

| start | title |
|---|---|
| 00:00 | Title and problem (54s) |
| 00:54 | Hidden states and user decisions (33s) |
| 01:27 | Architecture and truth separation (53s) |
| 02:20 | Acquisition and assumptions (48s) |
| 03:08 | MQTT contract (45s) |
| 03:53 | Data management (45s) |
| 04:38 | Model and identification (65s) |
| 05:43 | Evaluation T1–T3 (56s) |
| 06:40 | Evaluation T4–T5 (49s) |
| 07:29 | Integrated demo setup (20s) |
| 07:49 | Live dashboard overview (22s) |
| 08:11 | Apply an 18 A load (23s) |
| 08:34 | Inject cooling failure (23s) |
| 08:57 | Alarm explanation and safe load (19s) |
| 09:16 | What-if decision (22s) |
| 09:38 | SQLite data layer (14s) |
| 09:52 | LWT offline / stale data (22s) |
| 10:14 | Conclusion and limitations (41s) |
