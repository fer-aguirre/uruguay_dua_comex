# TODO

- [ ] Build `notebooks/0.0-collect-data.ipynb`: automate downloading the raw DUA zip files from DNA (aduanas.gub.uy) into `data/raw/<año>/`, so the pipeline no longer requires downloading them by hand.
- [ ] Build `notebooks/0.4-update-data.ipynb`: check whether DNA has published new months since the last run and, if so, re-run `0.1`→`0.2` to refresh `data/processed/` with the latest data.
- [ ] Update `README.md` with data availability info: how current the published dataset is and how often it gets refreshed.
