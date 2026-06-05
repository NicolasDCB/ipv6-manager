# IPv6 Manager

Sistema de gerenciamento e planejamento de endereços IPv6 com interface web.

## Estrutura

```
ipv6_app/
├── app.py              # Backend Flask + toda a lógica IPv6
├── requirements.txt    # Dependências
├── templates/
│   └── index.html      # Interface web
└── README.md
```

## Como rodar

### 1. Instalar dependências

```bash
pip install -r requirements.txt
```

### 2. Iniciar o servidor

```bash
python app.py
```

### 3. Abrir no navegador

```
http://localhost:5000
```

## Funcionalidades

- Conceitos fundamentais (Unicast, Multicast, Anycast)
- Plano hierárquico /32 → /48 → /56 → /64
- Validador de endereços IPv6
- Subdivisão de blocos
- Algoritmos Leftmost e Rightmost
- Simulação de clientes residenciais
- Endereços Anycast reservados
- Tabela de prefixos de referência

## Observações

- Desenvolvido sem uso da biblioteca `ipaddress` do Python
- Toda a lógica de manipulação IPv6 é implementada manualmente
- Bloco principal padrão: `2804:1f4a::/32` (alterável pela interface)
