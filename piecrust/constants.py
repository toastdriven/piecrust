# Enable all basic ORM filters but do not allow filtering across relationships.
ALL = 1
# Enable all ORM filters, including across relationships
ALL_WITH_RELATIONS = 2

# Ripped from Django.
QUERY_TERMS = dict([(x, None) for x in (
    'exact', 'iexact', 'contains', 'icontains', 'gt', 'gte', 'lt', 'lte', 'in',
    'startswith', 'istartswith', 'endswith', 'iendswith', 'range', 'year',
    'month', 'day', 'week_day', 'isnull', 'search', 'regex', 'iregex',
)])

LOOKUP_SEP = '__'
