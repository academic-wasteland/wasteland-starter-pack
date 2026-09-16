from wasteland.client import Client
from wasteland.residents import handle


def test_ask_preserves_operation_with_body():
    client = object.__new__(Client)
    client.name = 'yamatai'
    sent = []
    client.send = sent.append
    client.ask('ubar',operation='phenotype-search',body={'phenotypes':['HP:0001250']})
    assert sent[0]['body']['operation'] == 'phenotype-search'
    assert sent[0]['body']['phenotypes'] == ['HP:0001250']


def test_describe_publishes_interests_not_private_settings():
    config = {'name':'example','display':'Example','trust':{'blocked':[]},'residents':[
        {'name':'scholar','mode':'model','role':'Researcher','interests':['HPO'],
         'model':{'key_env':'SECRET_KEY'}}]}
    result=handle({'from':'ubar','body':{'operation':'describe'}},config)
    assert result['residents'][0]['interests'] == ['HPO']
    assert 'SECRET_KEY' not in str(result)
