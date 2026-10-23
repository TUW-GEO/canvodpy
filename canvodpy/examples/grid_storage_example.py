"""Example: Complete Grid Storage and Loading Workflow

Demonstrates how to:
1. Create a grid
2. Store it to an Icechunk store
3. Load it back later
4. Use it for VOD data processing
"""

from canvod.grids import create_hemigrid
from canvod.store import store_grid


def example_store_grids(store, grid_configs):
    """Store multiple grids to the store."""
    print("\n" + "=" * 70)
    print("STEP 1: Creating and Storing Grids")
    print("=" * 70)

    for config in grid_configs:
        grid = create_hemigrid(
            angular_resolution=config["resolution"],
            grid_type=config["type"],
        )
        grid_name = f"{config['type']}_{int(config['resolution'])}deg"
        snapshot_id = store_grid(grid=grid, store=store, grid_name=grid_name)
        print(f"  → {grid_name}: {snapshot_id[:16]}...")


def main():
    """Run complete example."""
    print("\n" + "=" * 70)
    print("Complete Grid Storage Example")
    print("=" * 70)
    print("""
This workflow shows:

1. CREATE and STORE grids:
   grid = create_hemigrid(angular_resolution=4, grid_type='equal_area')
   store_grid(grid, store, 'equal_area_4deg')

2. LOAD grids later:
   grid = load_grid(store, 'equal_area_4deg')

3. USE for processing:
   vod_ds = add_cell_ids_to_ds_fast(vod_ds, grid, 'equal_area_4deg')

Benefits:
- Store grids once, reuse across datasets
- Ensures consistency across processing runs
- Faster than recreating grids each time

Store structure:
  store/
    ├── reference_01_canopy_01/  # VOD data with cell_id_*
    ├── grids/
    │   ├── equal_area_2deg/     # Grid definitions
    │   └── htm_4deg/
""")


if __name__ == "__main__":
    main()
