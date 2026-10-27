"""Local spelling/transliteration matching; uncertain financial scopes require a click."""
import re
import unicodedata
from difflib import SequenceMatcher

_TRANSLIT=dict(zip('абвгдеёжзийклмнопрстуфхцчшщъыьэюя',('a','b','v','g','d','e','e','zh','z','i','y','k','l','m','n','o','p','r','s','t','u','f','h','ts','ch','sh','sch','','y','','e','yu','ya')))


def normalized(value):
    value=unicodedata.normalize('NFKC',value).casefold()
    return ' '.join(re.findall(r'[a-z0-9]+',''.join(_TRANSLIT.get(c,c) for c in value)))


def similar_names(rows,query):
    needle=normalized(query);compact=needle.replace(' ','')
    if len(compact)<4:return []
    size=len(needle.split());ranked=[]
    for row in rows:
        tokens=normalized(row['name']).split()
        variants=[''.join(tokens)]
        for width in range(max(1,size-1),size+2):
            variants.extend(''.join(tokens[i:i+width]) for i in range(len(tokens)-width+1))
        score=max((SequenceMatcher(None,compact,value,autojunk=False).ratio() for value in variants),default=0)
        if score>=0.72:ranked.append((score,row))
    ranked.sort(key=lambda pair:(-pair[0],pair[1]['id']))
    return [row for score,row in ranked[:8]]
