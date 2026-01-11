import json

data = json.load(open('SRD_Classes.json'))

print("=" * 80)
print("CLASS SUMMARY")
print("=" * 80)

for c in data['classes']:
    name = c.get('name', '?')
    bab = c.get('base_attack_bonus', '?')
    primary = c.get('primary_abilities', [])
    caster = c.get('caster_type', 'none')
    hit_die = c.get('hit_die', '?')
    spell_ability = c.get('spellcasting_ability', '')
    
    print(f"\n{name}")
    print(f"  BAB: {bab}")
    print(f"  Hit Die: {hit_die}")
    print(f"  Primary Stats: {primary}")
    print(f"  Caster Type: {caster}")
    if spell_ability:
        print(f"  Spellcasting Ability: {spell_ability}")
    
    # Check level 1 data
    levels = c.get('levels', {})
    lvl1 = levels.get('1', {})
    features = lvl1.get('features_at_level', [])
    cantrips = lvl1.get('cantrips_known', 0)
    spells = lvl1.get('spells_known', 0)
    slots = lvl1.get('spell_slots_by_level', {})
    
    if features:
        print(f"  Level 1 Features: {features}")
    if cantrips:
        print(f"  Cantrips Known: {cantrips}")
    if spells:
        print(f"  Spells Known: {spells}")
    if slots:
        print(f"  Spell Slots: {slots}")

print("\n" + "=" * 80)
