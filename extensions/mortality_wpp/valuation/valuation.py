"""Public mortality primitives from R04."""
import csv
from functools import lru_cache
from math import exp,isfinite
from hashlib import file_digest


def sha(path):
    with path.open('rb') as f:
        return file_digest(f,'sha256').hexdigest()


SEX_BY_CATEGORY = {'male60':'male','female55':'female','female50':'female'}


def validate_rate(value):
    if type(value) not in (int,float) or not isfinite(value) or value<=-1:
        raise ValueError('expected finite rate greater than minus one')


def discount(months,rate):
    validate_rate(rate)
    return (1.+rate)**(-months/12.)


class Mortality:
    def __init__(self,rates):
        self.rates=rates

    @classmethod
    def from_csv(cls,path):
        rates={}
        with path.open(encoding='utf-8-sig',newline='') as handle:
            for row in csv.DictReader(handle):
                k=int(row['year']),int(row['age']),row['sex']
                if k in rates:
                    raise ValueError('duplicate hazard cell')
                m=float(row['mx_per_person_year'])
                if not isfinite(m) or not 0<=m or not 40<=k[1]<100:
                    raise ValueError('invalid or open-ended mortality support')
                rates[k]=m
        return cls(rates)

    def hazard(self,sex,birth,t,fixed_period):
        year=t//12 if fixed_period is None else fixed_period
        age=(t-birth)//12
        try:
            return self.rates[year,age,sex]
        except KeyError:
            raise ValueError(f'Mortality support unavailable for {year}, age {age}, {sex}') from None

    @lru_cache(maxsize=5000)
    def month_survival(self,sex,birth,start,end,fixed_period,scale=1.):
        """S(end|start) from calendar-month beginnings and last birthday ages."""
        if not isfinite(scale) or scale<0 or end<start:
            raise ValueError('invalid survival scale or ordering')
        if end>birth+100*12:
            raise ValueError('No tail hazard beyond the 100-year cutoff')
        values=[1.]
        intensity=0.
        for t in range(start,end):
            intensity+=self.hazard(sex,birth,t,fixed_period)*scale/12
            values.append(exp(-intensity))
        return tuple(values)


def validate_public_source(directory):
    import json
    manifest=json.loads((directory/'source_manifest.json').read_text(encoding='utf-8'))
    path=directory/'wpp2024_china_mortality_40_99.csv'
    if sha(path)!=manifest['output_sha256']:
        raise ValueError('public mortality extract integrity mismatch')
    return path
