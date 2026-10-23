# Preprocessing runs only when the settings ask for it

Preprocessing (temporal aggregation, grid assignment) changes the stored
data, so it is never a default. When the settings file sets it, every run
applies it, whichever entry point starts the run (command line, Python, Airflow), so
a store never mixes data processed in different ways.
