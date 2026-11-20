# Printastic 360

O frontend está em `printastic360.html` para publicação no GitHub Pages. A VPS Windows corre a API e o PostgreSQL. O aplicativo existente continua a gerir as encomendas que já estão no Hub. Nesta fase, as linhas do planeamento são registadas no próprio módulo.

## Execução na VPS

- Criar uma base PostgreSQL e um utilizador dedicado com acesso à base. Manter o PostgreSQL acessível por loopback.
- Criar um ambiente Python com `py -3.13 -m venv .venv` e instalar as dependências com `.\.venv\Scripts\python.exe -m pip install -r printastic360-requirements.txt`.
- Configurar `P360_DATABASE_URL` e `P360_TOKEN` no processo da API. Usar uma chave aleatória com pelo menos 32 caracteres. Os valores ficam na VPS.
- Iniciar com `.\.venv\Scripts\python.exe printastic360-api.py`. A API cria as duas tabelas de trabalho e escuta em `127.0.0.1:8310`. Configurar arranque automático sob uma conta dedicada.
- Encaminhar `/production` e os subcaminhos por um proxy HTTPS com certificado válido. Usar a origem desse proxy no formulário de ligação. O frontend oficial usa a origem `https://printastic-al.github.io`.
- Verificar `GET /production` com e sem a chave de acesso. Programar a cópia da base para destino externo e validar o restauro.

## Âmbito da primeira entrega

O planeamento dá prioridade ao prazo, atribui stock disponível às encomendas por essa ordem, agrega as compras em falta e estima o custo com base na ficha de produto. Concluir uma linha guarda o seu estado e desconta o stock registado, até ao limite disponível.

O custo é registado manualmente nesta versão. Ficam pendentes a recolha de preços a partir dos fornecedores, a pesquisa de alternativas, a integração com o Hub, a migração do Odoo Online, clientes, orçamentos, pagamentos, notas de encomenda/PDF e inteligência comercial (previsão, sazonalidade e recomendações). A faturação oficial continua na AT. O orçamento inicial de disco é inferior a 20 GB, com cerca de 50 GB livres na VPS, sem modelos locais pesados.
