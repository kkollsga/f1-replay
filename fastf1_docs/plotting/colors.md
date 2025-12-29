# Plotting: Colors & Styles

## Setup

```python
from fastf1 import plotting

# Initialize matplotlib with F1 styles
plotting.setup_mpl(mpl_timedelta_format='%H:%M:%S', misc_timedelta_format='%H:%M:%S')
```

## Driver Colors

```python
plotting.get_driver_color(driver)
```
Get official color for driver.
- `driver` (str): Driver number or abbreviation
- Returns: hex color string

```python
plotting.get_driver_abbreviation(driver)
```
Get 3-letter driver code.

```python
plotting.get_driver_abbreviations_by_team(team)
```
Get all drivers for a team.

### Usage

```python
from fastf1 import plotting

ver_color = plotting.get_driver_color('VER')
ver_abbr = plotting.get_driver_abbreviation('1')
print(f"Verstappen ({ver_abbr}): {ver_color}")
```

## Team Colors

```python
plotting.get_team_color(team)
```
Get official team color.
- `team` (str): Team name (e.g., 'Red Bull Racing')
- Returns: hex color string

```python
plotting.get_team_name(abbreviation)
```
Get full team name from abbreviation.

```python
plotting.list_team_names()
```
List all F1 teams.

## Tire Compounds

```python
plotting.get_compound_color(compound)
```
Get color for tire compound.
- `compound` (str): 'soft', 'medium', 'hard', 'inter', 'wet'
- Returns: hex color string

```python
plotting.list_compounds()
```
List all available compounds.

### Usage

```python
soft_color = plotting.get_compound_color('soft')
hard_color = plotting.get_compound_color('hard')
```

## Legends & Styling

```python
plotting.add_sorted_driver_legend(ax, position='upper left')
```
Add driver legend sorted by position.
- `ax`: matplotlib axis
- `position` (str): Legend position

```python
plotting.set_default_colormap('tab10')
```
Set default color palette.

