# Bug Fix: Province Neighbor Inconsistencies

**Problem:** Some provinces had invalid or missing neighbors, causing army movement to work incorrectly or allow movement to anywhere on the map.

## Root Cause
The bug was in `export_to_opengs.py` in the `export_provinces_txt()` function. When building the neighbor list from the ID map, the code was including all neighbors without filtering them against the actual provinces that exist in `Provinces.txt`. This caused:

1. **Orphaned neighbors**: References to province IDs that don't exist in `Provinces.txt`
2. **Inconsistent maps**: The ID map calculation could detect neighbors that aren't actually written to the output file
3. **Sea province issues**: Sea region neighbors weren't validated either

## Fixes Applied

### Fix 1: Land Province Neighbor Filtering (Line ~1372)
**Before:**
```python
neighbor_ids = ",".join(str(n) for n in neighbors_by_pid.get(int(pid), []))
```

**After:**
```python
# Filter neighbors to only include those that exist in pid_to_color (i.e., provinces in Provinces.txt)
all_neighbors = neighbors_by_pid.get(int(pid), [])
valid_neighbors = [n for n in all_neighbors if n in pid_to_color]
neighbor_ids = ",".join(str(n) for n in valid_neighbors)
```

**Impact:** Land provinces now only reference neighbors that actually exist in the output file.

### Fix 2: Sea Province Neighbor Filtering (Line ~1386)
**Before:**
```python
neighbor_ids = ",".join(str(n) for n in neighbors_by_pid.get(int(sea_id), []))
```

**After:**
```python
# Filter neighbors to include only land provinces (pid_to_color) and other sea IDs (sea_items)
all_neighbors = neighbors_by_pid.get(int(sea_id), [])
valid_sea_ids = {int(s_id) for _, s_id in sea_items}
valid_neighbors = [n for n in all_neighbors if n in pid_to_color or n in valid_sea_ids]
neighbor_ids = ",".join(str(n) for n in valid_neighbors)
```

**Impact:** Sea regions now correctly reference only existing land provinces and other sea regions.

### Fix 3: Debug Output and Validation (Lines ~1396-1438)
Added comprehensive debug output to detect:
- **Orphaned provinces**: Province IDs that appear in neighbors but aren't in `Provinces.txt`
- **Provinces without neighbors**: Land provinces with empty neighbor lists
- **Invalid neighbor references**: Provinces referencing IDs that don't exist

Example debug output:
```
[ERROR] N ORPHANED provinces in neighbors but NOT in Provinces.txt: [...]
[WARNING] N land provinces with NO neighbors: [...]
[WARNING] N provinces with invalid neighbor references
[OK] All neighbors are valid - no orphaned or invalid references detected.
```

### Fix 4: Unmapped Sea Pixel Detection (Lines ~1330-1335)
Added detection for sea pixels that remain unmapped after sea ID assignment. These would indicate a corruption in the province map PNG or missing sea color mappings.

```python
# DEBUG: Check if there are any unmapped sea pixels (ID = -1)
unmapped_sea_pixels = np.sum(full_id_map < 0)
if unmapped_sea_pixels > 0:
    print(f"[WARNING] {unmapped_sea_pixels} sea pixesl remained unmapped...")
```

## How to Test

Run `export_to_opengs.py` and look for:

1. **No errors about orphaned provinces**
2. **No provinces with invalid references**
3. **Message: [OK] All neighbors are valid**
4. **No unmapped sea pixel warnings**

If these pass, the neighbor data is consistent and valid.

## Files Modified
- `c:\RP\map_generator_godot\build_map\src\export_to_opengs.py`
  - `export_provinces_txt()` function: Added neighbor filtering and validation

## Technical Details

The neighbor calculation works like this:

1. `_build_neighbor_lookup()` reads the `full_id_map` (which includes land province IDs and sea region IDs)
2. It detects borders where neighboring pixels have different IDs
3. These are recorded as undirected neighbor relationships
4. **NEW**: These relationships are filtered to ensure both sides actually exist in the output

The fix ensures that the runtime game engine will only see valid province references and won't crash or allow invalid movement because of orphaned neighbor records.
