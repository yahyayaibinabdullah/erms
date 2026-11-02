"""Read-only checks for final-schema SQL; dollar-quoted function bodies are opaque."""
import re


def statements(source):
    """Split PostgreSQL SQL outside quoted strings, identifiers and comments."""
    result=[];part=[];i=0;quote=None;dollar=None;block=0
    while i<len(source):
        c=source[i];pair=source[i:i+2]
        if dollar:
            if source.startswith(dollar,i):part.append(dollar);i+=len(dollar);dollar=None
            else:part.append(c);i+=1
            continue
        if quote:
            part.append(c);i+=1
            if c==quote:
                if i<len(source) and source[i]==quote:part.append(source[i]);i+=1
                else:quote=None
            elif c=='\\' and quote=="'" and i<len(source):part.append(source[i]);i+=1
            continue
        if block:
            if pair=='/*':block+=1;i+=2
            elif pair=='*/':block-=1;i+=2
            else:i+=1
            continue
        if pair=='--':
            end=source.find('\n',i);i=len(source) if end<0 else end;part.append('\n');continue
        if pair=='/*':block=1;i+=2;part.append(' ');continue
        if c in ('"',"'"):quote=c;part.append(c);i+=1;continue
        if c=='$':
            match=re.match(r'\$[A-Za-z_0-9]*\$',source[i:])
            if match:dollar=match.group();part.append(dollar);i+=len(dollar);continue
        if c==';':
            if ''.join(part).strip():result.append(''.join(part).strip())
            part=[];i+=1;continue
        part.append(c);i+=1
    if quote or dollar or block:raise ValueError('Unterminated SQL quote or comment')
    if ''.join(part).strip():result.append(''.join(part).strip())
    return result


def assert_canonical(source):
    items=statements(source)
    assert sum(s.upper()=='BEGIN' for s in items)==1,'Canonical schema needs one transaction'
    assert sum(s.upper()=='COMMIT' for s in items)==1,'Canonical schema needs one transaction'
    seen=set();preflights=0
    for statement in items:
        assert not re.match(r'(INSERT|UPDATE|DELETE|DROP|TRUNCATE)\b',statement,re.I),'Data or upgrade operation in canonical schema: '+statement[:100]
        assert not re.match(r'CREATE OR REPLACE\b',statement,re.I),'Edit final definitions in place; do not append replacements'
        assert not statement.startswith('\\'),'psql client commands are not PostgreSQL SQL'
        if re.match(r'DO\b',statement,re.I):
            preflights+=1
            assert preflights==1 and 'server_version_num' in statement and 'pg_ts_config' in statement,'Only the read-only PostgreSQL readiness preflight belongs here'
            assert not re.search(r'\b(INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|TRUNCATE|EXECUTE)\b',statement,re.I),'Upgrade/data repair inside a DO block'
        if re.match(r'ALTER TABLE\b',statement,re.I):
            assert not re.search(r'\b(DROP|RENAME|ADD COLUMN|ALTER COLUMN\s+\S+\s+TYPE)\b',statement,re.I),'Put final columns in CREATE TABLE; do not replay column changes'

        match=re.match(r'CREATE FUNCTION\s+(\S+)\((.*?)\)\s+RETURNS\b',statement,re.I|re.S)
        if match:
            key=(match[1],re.sub(r'\s+',' ',match[2]))
            assert key not in seen,'Repeated function signature: '+match[1]
            seen.add(key)
    return {'statements':len(items),'functions':len(seen)}
