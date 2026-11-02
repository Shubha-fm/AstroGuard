# AstroGuard-QFV 18K: professional result filenames

This small update removes temporary `SEND_ME...` report filenames for future output archives and renames existing archives. It does **not** alter the 18,000-object cohort, trained weights, experiment configuration, model predictions, or TLC models.

## On macOS

1. Download `AstroGuard_QFV_18K_File_Naming_Patch.zip` to Downloads.
2. In Terminal, run:

```bash
cd ~/Downloads/AstroGuard_18K_macOS_Fresh_Start
unzip -o ~/Downloads/AstroGuard_QFV_18K_File_Naming_Patch.zip -d .
.venv/bin/python rename_outputs.py
```

The script is idempotent: it can be run again. Before editing each modified source file, it saves a `*.before_filename_update` backup next to it. It renames existing report ZIPs **without rebuilding them**. The code for generating future ZIPs also gets the new names.

## Renamed output files

| Folder | New file |
|---|---|
| `RESULTS_18K/` | `AstroGuard_QFV_18K_Collection_Summary.zip` |
| `RESULTS_18K/classical/` | `AstroGuard_QFV_18K_Classical_Results.zip` |
| `RESULTS_18K/matched/` | `AstroGuard_QFV_18K_Matched_Results.zip` |
| `RESULTS_18K/smoke/` | `AstroGuard_QFV_18K_Smoke_Results.zip` |
| `RESULTS_18K/quantum_sanity/` | `AstroGuard_QFV_18K_Quantum_Sanity_Results.zip` |
| `RESULTS_18K/independent/` | `AstroGuard_QFV_18K_Independent_Labels.zip` |

These ZIPs are **compact reports** and do not contain the full ~3 GB dataset or all trained checkpoints. Keep the full `input/` and `RESULTS_18K/` directories as research evidence.

## Reproducibility note

The filename-only patch changes source-code hashes for a few Python files. Do not misrepresent the patched source hashes as hashes of the files used during the original experiments. Preserve the `*.before_filename_update` backups and the original experiment provenance. For a GitHub release, record this as a **report-naming-only change**, with no numerical recomputation.
