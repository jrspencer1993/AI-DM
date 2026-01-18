import json

data = json.load(open('SRD_Equipment.json'))

print("=" * 60)
print("ARMOR")
print("=" * 60)
armor = [e for e in data if e.get('equipment_category') == 'Armor']
print(f"Total armor items: {len(armor)}")
print()

for a in armor:
    name = a.get('name', '?')
    ac = a.get('armor_class', {})
    armor_cat = a.get('armor_category', '?')
    print(f"  {name}: category={armor_cat}, AC={ac}")

print()
print("=" * 60)
print("WEAPONS")
print("=" * 60)
weapons = [e for e in data if e.get('equipment_category') == 'Weapon']
print(f"Total weapons: {len(weapons)}")
print()

for w in weapons[:15]:
    name = w.get('name', '?')
    wcat = w.get('weapon_category', '?')
    wrange = w.get('weapon_range', '?')
    dmg = w.get('damage', {})
    dice = dmg.get('damage_dice', '?')
    dtype = dmg.get('damage_type', {})
    if isinstance(dtype, dict):
        dtype = dtype.get('name', '?')
    props = [p.get('name', '?') if isinstance(p, dict) else p for p in w.get('properties', [])]
    print(f"  {name}: {wcat} {wrange}, {dice} {dtype}, props={props}")
