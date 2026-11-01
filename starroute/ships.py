"""Ship type/grade definitions. No navigation, pricing or event mechanics."""
from dataclasses import dataclass, asdict
from .model import integer

SHIP_TYPES = frozenset(('normal', 'armed_cruiser', 'engineering'))

@dataclass(frozen=True)
class ShipGrade:
    id: str
    rank: int

@dataclass(frozen=True)
class ShipProfile:
    ship_id: str
    ship_type: str | None
    grade_id: str | None
    normal_speed: int | None
    max_warp_speed: int | None
    purchase_price: int | None
    insurance_premium: int | None
    specification_status: str

    def dto(self):
        return asdict(self)


def build_ship_models(data, identifier):
    """Format 1 stays byte-for-byte canonical; missing decisions remain None.

    Format 2 explicitly marks proposed values as provisional or confirmed.
    Integers here are configurable model values, not a selected warp formula.
    """
    grades = {}
    profiles = {}
    if data['format_version'] == 1:
        if 'ship_grades' in data or any('profile' in s for s in data['ships']):
            raise ValueError('ship extensions require format_version 2')
        for ship in data['ships']:
            profiles[ship['id']] = ShipProfile(ship['id'],None,None,None,None,None,None,'legacy')
        return grades, profiles
    rows = data['ship_grades']
    if not isinstance(rows,list):
        raise ValueError('ship_grades')
    ranks = set()
    for row in rows:
        key = identifier(row['id'])
        rank = integer(row['rank'],1)
        if key in grades or rank in ranks:
            raise ValueError('duplicate grade or rank')
        grades[key] = ShipGrade(key,rank)
        ranks.add(rank)
    for ship in data['ships']:
        row = ship['profile']
        if not isinstance(row,dict) or set(row) != {'ship_type','grade_id','normal_speed','max_warp_speed','purchase_price','insurance_premium','specification_status'}:
            raise ValueError('ship profile fields')
        if row['ship_type'] not in SHIP_TYPES:
            raise ValueError('ship type')
        if row['grade_id'] is not None and identifier(row['grade_id']) not in grades:
            raise ValueError('unknown grade')
        if row['specification_status'] not in ('provisional','confirmed'):
            raise ValueError('specification status')
        for key in ('normal_speed','max_warp_speed','purchase_price','insurance_premium'):
            if row[key] is not None:
                integer(row[key],1 if key.endswith('speed') else 0)
        if row['specification_status']=='confirmed' and any(v is None for v in row.values()):
            raise ValueError('confirmed profile must be complete')
        profiles[ship['id']] = ShipProfile(ship['id'],**row)
    validate_relationships(data, grades, profiles)
    return grades, profiles


def validate_relationships(data, grades, profiles):
    capacities = {s['id']:s['capacity'] for s in data['ships']}
    def compare(left,right,relation,label):
        if left is not None and right is not None and not relation(left,right):
            raise ValueError(label)
    equal=lambda a,b:a==b
    greater=lambda a,b:a>b
    less=lambda a,b:a<b
    normals=[p for p in profiles.values() if p.ship_type=='normal']
    for standard in normals:
        for other in profiles.values():
            if other.ship_type=='normal':
                compare(other.normal_speed,standard.normal_speed,equal,'normal speed independent of grade')
                if other.grade_id is not None and standard.grade_id is not None and grades[other.grade_id].rank>grades[standard.grade_id].rank:
                    compare(capacities[other.ship_id],capacities[standard.ship_id],greater,'higher grade capacity')
                    for key in ('max_warp_speed','purchase_price','insurance_premium'):
                        compare(getattr(other,key),getattr(standard,key),greater,'higher grade '+key)
            if other.grade_id is None or other.grade_id!=standard.grade_id:
                continue
            if other.ship_type not in ('armed_cruiser','engineering'):
                continue
            compare(capacities[other.ship_id],capacities[standard.ship_id],equal,'same grade capacity')
            compare(other.purchase_price,standard.purchase_price,greater,'special ship price')
            if other.ship_type=='armed_cruiser':
                compare(other.normal_speed,standard.normal_speed,equal,'armed normal speed')
                compare(other.max_warp_speed,standard.max_warp_speed,equal,'armed max warp speed')
                compare(other.insurance_premium,standard.insurance_premium,less,'armed insurance')
            else:
                compare(other.normal_speed,standard.normal_speed,less,'engineering normal speed')
                compare(other.max_warp_speed,standard.max_warp_speed,less,'engineering max warp speed')
