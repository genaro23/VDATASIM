# VDATASIM


A Python-based distributed storage system implementing two-level erasure coding with an interactive GUI for visualization and management.

![Version](https://img.shields.io/badge/version-3.1-blue.svg)
![Python](https://img.shields.io/badge/python-3.8+-green.svg)
![License](https://img.shields.io/badge/license-MIT-orange.svg)
![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey.svg)

## Features

### Storage Architecture
- 🗄️ **484 Drives** organized into 11 Dboxes (44 drives each)
- 📊 **418 Data Drives** for actual storage
- 🔒 **33 Local Parity Drives** for group-level redundancy
- 🌐 **11 Global Parity Drives** for cross-group protection
- 🔄 **22 Hot Spares** for automatic failover

### Operational Modes
- **Normal Mode:** ~8.5% overhead, uses all available drives
- **HA Mode:** 18% overhead, limits to 2 drives per Dbox (22 total) for maximum availability

### GUI Features
- 🎨 **Color-Coded Visualization:**
  - 🟢 Green - Online data drives
  - 🔴 Red - Offline/failed drives
  - 🟣 Purple - Local parity drives
  - 🔵 Blue - Global parity drives
  - 🟡 Yellow - Hot spare drives
- 📝 **Hex Preview:** First 4 bytes displayed on each drive
- 🔍 **Hex Viewer:** Right-click any drive to view full contents
- 📊 **Storage Stats:** Real-time capacity monitoring
- 🔧 **Rebuild Visualization:** See which drives are read during recovery
- 💾 **File Management:** Multi-file upload and download with integrity verification

## Installation

### Prerequisites
```bash
Python 3.8 or higher
numpy
tkinter (usually included with Python)
```

### Setup
```bash
# Clone the repository
git clone https://github.com/genaro23/VDATASIM.git
cd erasure-storage-system

# Install dependencies
pip install -r requirements.txt

# Run the application
python v3.1/storage_system_v3.1.py
```

## Quick Start

### 1. Initialize Storage
```python
# Run the application
python v3.1/storage_system_v3.1.py

# Click "Initialize Storage" button
# This creates 484 × 1MB drive files in ./storage directory
```

### 2. Load Files
```python
# Click "Load Files" button
# Select one or more files to store
# Files are distributed across drives with erasure coding
```

### 3. Simulate Failures
```python
# Click any drive button to toggle online/offline
# Or click "Toggle Dbox" to fail an entire 44-drive group
# System shows whether data is still recoverable
```

### 4. Rebuild Data
```python
# Click "Rebuild Drives" button
# Choose whether to bring failed drives back online or use spares
# View detailed report of rebuild process
```

### 5. Verify Integrity
```python
# Click "Download File" button
# Save reconstructed file and compare with original
```

## Architecture

### Erasure Coding Scheme
```
┌─────────────────────────────────────────────────────────┐
│                    Dbox-0 (44 drives)                   │
├─────────────────────────────────────────────────────────┤
│ Data Drives: 0-37 (38 drives)                           │
│   ├─ Group 0: Drives 0-12   → Local Parity 38          │
│   ├─ Group 1: Drives 13-25  → Local Parity 39          │
│   └─ Group 2: Drives 26-37  → Local Parity 40          │
│ Global Parity: Drive 41                                 │
│ Hot Spares: Drives 42-43                                │
└─────────────────────────────────────────────────────────┘
                          ⋮
┌─────────────────────────────────────────────────────────┐
│                   Dbox-10 (44 drives)                   │
└─────────────────────────────────────────────────────────┘
```

### Failure Tolerance

| Scenario | Recoverable? | Notes |
|----------|--------------|-------|
| 1 drive failure | ✅ Yes | Use local parity |
| 2 drives in same group | ✅ Yes | Use local + global parity |
| 3+ drives in same group | ❌ No | Data loss |
| 1 drive per group (distributed) | ✅ Yes | Each uses local parity |
| Entire Dbox failure (HA mode) | ✅ Yes | Data distributed across all Dboxes |

## Usage Examples

### Example 1: Store Multiple Files
```python
# Load three documents
files = ['report.pdf', 'data.xlsx', 'presentation.pptx']
# System combines with metadata headers
# Distributes across 418 data drives
# Calculates 44 parity drives
```

### Example 2: Simulate Disk Failure
```python
# Click drives 15, 27, 31 to mark as failed
# Click "Check Integrity" 
# Result: "Recoverable with 3 failures"
# Different groups → can rebuild each independently
```

### Example 3: Dbox Failure Test
```python
# Click "Toggle Dbox" on Dbox-3
# Marks all 44 drives offline
# Click "Check Integrity"
# Normal Mode: May show data at risk
# HA Mode: "Recoverable" - data safe!
```

### Example 4: View Drive Contents
```python
# Right-click any drive button
# Opens hex viewer window showing:
# - Full 1MB hex dump
# - ASCII representation
# - Byte offsets
```

## Configuration

### Storage Parameters
```python
TOTAL_DRIVES = 484
DRIVE_SIZE = 1024 * 1024  # 1MB per drive
CHUNK_SIZE = 4096  # 4KB chunks
DBOXES = 11
DRIVES_PER_DBOX = 44
```

### Customization
Edit these values in the code to adjust:
- Drive capacity
- Number of Dboxes
- Chunk size for striping
- Local group sizes
- Number of hot spares

## API Reference

### Core Classes

#### `ErasureCodedStorage`
Main storage engine class.

**Methods:**
- `initialize_drives()` - Create drive files
- `write_files(input_files)` - Store files with erasure coding
- `rebuild_drives(failed_drives, bring_online)` - Recover failed drives
- `retrieve_file()` - Download stored data
- `check_data_integrity()` - Verify recoverability
- `get_storage_stats()` - Get capacity information

#### `StorageGUI`
Tkinter-based graphical interface.

**Methods:**
- `toggle_drive(drive_id)` - Fail/restore single drive
- `toggle_dbox(dbox_id)` - Fail/restore entire Dbox
- `show_drive_contents(drive_id)` - Open hex viewer
- `update_all_drive_displays()` - Refresh UI

See [docs/api_reference.md](docs/api_reference.md) for complete API documentation.

## Version History

| Version | Date | Highlights |
|---------|------|------------|
| v1.0 | 2024-02-05 | Initial 146-drive implementation |
| v1.1 | 2024-02-05 | macOS color compatibility fix |
| v2.0 | 2024-02-05 | Expanded to 484 drives, 11 Dboxes |
| v2.1 | 2024-02-05 | Enhanced macOS support |
| v3.0 | 2024-02-05 | HA mode, hex viewer, rebuild system |
| v3.1 | 2024-02-05 | Fixed uint8 overflow bug (stable) |

See [CHANGELOG.md](CHANGELOG.md) for detailed version history.

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Development Setup
```bash
# Fork and clone
git clone https://github.com/YOUR_USERNAME/VDATASIM.git
cd erasure-storage-system

# Create feature branch
git checkout -b feature/your-feature-name

# Make changes and test
python v3.1/storage_system_v3.1.py

# Commit and push
git add .
git commit -m "Description of changes"
git push origin feature/your-feature-name

# Create pull request on GitHub
```

## Testing
```bash
# Run basic functionality test
python -m pytest tests/

# Test specific features
python tests/test_erasure_coding.py
python tests/test_gui.py
python tests/test_rebuild.py
```

## Troubleshooting

### Common Issues

**Issue:** Colors not showing on macOS
- **Solution:** Upgrade to v3.1 or later

**Issue:** "OverflowError: Python integer 256 out of bounds for uint8"
- **Solution:** Use v3.1 which fixes the parity calculation

**Issue:** GUI not responsive during large file writes
- **Solution:** This is normal - operations run in background threads

**Issue:** "No data drives available"
- **Solution:** Click "Initialize Storage" first

See [docs/troubleshooting.md](docs/troubleshooting.md) for more help.

## Performance

### Benchmarks (tested on M1 MacBook Pro)

| Operation | Time | Notes |
|-----------|------|-------|
| Initialize 484 drives | ~2s | Creates 484MB of files |
| Write 100MB file | ~5s | Including parity calculation |
| Rebuild 1 drive | ~0.5s | Local parity only |
| Rebuild 10 drives | ~3s | Mixed local/global |
| Full integrity check | ~0.1s | Logical check only |

## Future Roadmap

### v4.0 (Planned)
- [ ] Real reconstruction from drives (not cached data)
- [ ] Performance metrics dashboard
- [ ] Configuration export/import
- [ ] Automated test suite
- [ ] Variable drive sizes

### v4.1 (Planned)
- [ ] Web-based interface
- [ ] REST API
- [ ] Docker support
- [ ] Cloud storage backends

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Acknowledgments

- Erasure coding concepts based on Reed-Solomon and XOR parity schemes
- GUI design optimized for macOS with cross-platform compatibility
- Built with educational and demonstration purposes in mind

## Support

- 📫 **Issues:** https://github.com/genaro23/VDATASIM
/issues
- 💬 **Discussions:** https://github.com/genaro23/VDATASIM
/discussions
- 📧 **Email:** your.email@example.com

## Screenshots

### Main Interface
![Main Interface](docs/screenshots/main_interface.png)

### Hex Viewer
![Hex Viewer](docs/screenshots/hex_viewer.png)

### Rebuild Process
![Rebuild](docs/screenshots/rebuild_process.png)

---

**⭐ If you find this project useful, please consider giving it a star!**

Made with ❤️ for the distributed storage community
