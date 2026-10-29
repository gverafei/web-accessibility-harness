"""Normalize observed category labels independently of any selector."""
from .contracts import ContractError

def category_vocabulary(values):
    if not isinstance(values, (list, tuple)):
        raise ContractError('Invalid category vocabulary')
    result=[]
    for value in values:
        if not isinstance(value,str) or not value.strip() or len(value)>240:
            raise ContractError('Invalid category label')
        label=' '.join(value.split()).casefold()
        if label not in ('unknown','unclassified'):result.append(label)
    if len(set(result))>128:raise ContractError('At most 128 distinct categories are supported')
    return sorted(set(result))
