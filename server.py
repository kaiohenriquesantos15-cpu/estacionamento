
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import sqlite3
import os

app = Flask(__name__, static_folder='.')
CORS(app)

DB_PATH = os.path.join(os.path.dirname(__file__), 'estacionamento.db')

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    with get_db_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS clientes (
                id    INTEGER PRIMARY KEY AUTOINCREMENT,
                nome  VARCHAR(30) NOT NULL,
                fone  VARCHAR(15),
                cpf   VARCHAR(14) UNIQUE,
                data_cadastro DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS veiculos (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                placa       VARCHAR(10) NOT NULL UNIQUE,
                modelo      VARCHAR(30),
                marca       VARCHAR(30),
                cor         VARCHAR(20),
                cliente_id  INTEGER NOT NULL,
                data_cadastro DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (cliente_id) REFERENCES clientes(id)
            );

            CREATE TABLE IF NOT EXISTS precos (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                tipo_veiculo  VARCHAR(20) NOT NULL,
                valor_hora    DECIMAL(10,2) NOT NULL,
                valor_diaria  DECIMAL(10,2) NOT NULL
            );

            CREATE TABLE IF NOT EXISTS estadia (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                veiculo_id       INTEGER NOT NULL,
                vaga             INTEGER,
                horario_entrada  DATETIME NOT NULL,
                horario_saida    DATETIME,
                valor_total      DECIMAL(10,2),
                status           VARCHAR(20) DEFAULT 'ABERTA',
                FOREIGN KEY (veiculo_id) REFERENCES veiculos(id)
            );

            CREATE TABLE IF NOT EXISTS pagamentos (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                estadia_id       INTEGER NOT NULL,
                forma_pagamento  VARCHAR(20),
                valor_pago       DECIMAL(10,2),
                data_pago        DATETIME,
                FOREIGN KEY (estadia_id) REFERENCES estadia(id)
            );
        """)
        conn.commit()

# --- ROTAS DA API ---
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

# CLIENTES
@app.route('/api/clientes', methods=['GET'])
def get_clientes():
    with get_db_connection() as conn:
        clientes = conn.execute('SELECT * FROM clientes ORDER BY id DESC').fetchall()
    return jsonify([dict(c) for c in clientes])

@app.route('/api/clientes', methods=['POST'])
def add_cliente():
    data = request.json
    if not data.get('nome') or not data.get('cpf'):
        return jsonify({'error': 'Nome e CPF são obrigatórios.'}), 400

    with get_db_connection() as conn:
        existente = conn.execute('SELECT nome FROM clientes WHERE cpf = ?', (data['cpf'],)).fetchone()
        if existente:
            return jsonify({'error': f"CPF já cadastrado para o cliente: {existente['nome']}."}), 400
        
        cursor = conn.execute('INSERT INTO clientes (nome, cpf, fone) VALUES (?, ?, ?)', (data['nome'], data['cpf'], data.get('fone')))
        conn.commit()
        return jsonify({'id': cursor.lastrowid}), 201

# VEÍCULOS
@app.route('/api/veiculos', methods=['GET'])
def get_veiculos():
    with get_db_connection() as conn:
        veiculos = conn.execute("""
            SELECT v.*, c.nome AS cliente_nome 
            FROM veiculos v LEFT JOIN clientes c ON c.id = v.cliente_id ORDER BY v.id DESC
        """).fetchall()
    return jsonify([dict(v) for v in veiculos])

@app.route('/api/veiculos', methods=['POST'])
def add_veiculo():
    data = request.json
    with get_db_connection() as conn:
        try:
            cursor = conn.execute("""
                INSERT INTO veiculos (placa, modelo, marca, cor, cliente_id, data_cadastro) 
                VALUES (?, ?, ?, ?, ?, datetime('now', 'localtime'))
            """, (data.get('placa'), data.get('modelo'), data.get('marca'), data.get('cor'), data.get('cliente_id')))
            conn.commit()
            return jsonify({'id': cursor.lastrowid}), 201
        except sqlite3.IntegrityError as e:
            return jsonify({'error': str(e)}), 400

# PREÇOS E ESTADIAS
@app.route('/api/precos', methods=['GET'])
def get_precos():
    with get_db_connection() as conn:
        # O seu JS espera a propriedade 'valor_hora'
        return jsonify([dict(p) for p in conn.execute('SELECT * FROM precos').fetchall()])

@app.route('/api/estadias/abertas', methods=['GET'])
def get_estadias_abertas():
    with get_db_connection() as conn:
        estadias = conn.execute("""
            SELECT e.id, e.veiculo_id, e.vaga, e.horario_entrada, v.placa, c.nome AS cliente_nome, c.id AS cliente_id
            FROM estadia e JOIN veiculos v ON v.id = e.veiculo_id JOIN clientes c ON c.id = v.cliente_id
            WHERE e.status = 'ABERTA'
        """).fetchall()
    return jsonify([dict(e) for e in estadias])

@app.route('/api/estadias/saida/<placa>', methods=['GET'])
def get_estadia_saida(placa):
    with get_db_connection() as conn:
        est = conn.execute("""
            SELECT e.*, v.placa FROM estadia e JOIN veiculos v ON v.id = e.veiculo_id 
            WHERE v.placa = ? AND e.status = 'ABERTA'
        """, (placa,)).fetchone()
    if not est: return jsonify({'error': 'Veículo não encontrado no pátio.'}), 404
    return jsonify(dict(est))

@app.route('/api/estadias', methods=['POST'])
def add_estadia():
    data = request.json
    with get_db_connection() as conn:
        veiculo = conn.execute('SELECT cliente_id FROM veiculos WHERE id = ?', (data.get('veiculo_id'),)).fetchone()
        if not veiculo: return jsonify({'error': 'Veículo não encontrado.'}), 404

        carro_no_patio = conn.execute("""
            SELECT e.id FROM estadia e JOIN veiculos v ON v.id = e.veiculo_id 
            WHERE v.cliente_id = ? AND e.status = 'ABERTA'
        """, (veiculo['cliente_id'],)).fetchone()

        if carro_no_patio: return jsonify({'error': 'Este cliente já possui um veículo no estacionamento!'}), 400

        try:
            cursor = conn.execute("""
                INSERT INTO estadia (veiculo_id, vaga, horario_entrada, status)
                VALUES (?, ?, datetime('now','localtime'), 'ABERTA')
            """, (data.get('veiculo_id'), data.get('vaga')))
            conn.commit()
            return jsonify({'id': cursor.lastrowid}), 201
        except Exception as e:
            return jsonify({'error': str(e)}), 400

@app.route('/api/estadias/<int:id>/saida', methods=['PUT'])
def finalizar_estadia(id):
    with get_db_connection() as conn:
        conn.execute("""
            UPDATE estadia SET horario_saida = datetime('now','localtime'), valor_total = ?, status = 'FINALIZADA' WHERE id = ?
        """, (request.json.get('valor_total'), id))
        conn.commit()
    return '', 204

@app.route('/api/pagamentos', methods=['POST'])
def add_pagamento():
    data = request.json
    with get_db_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO pagamentos (estadia_id, forma_pagamento, valor_pago, data_pago)
            VALUES (?, ?, ?, datetime('now','localtime'))
        """, (data.get('estadia_id'), data.get('forma_pagamento'), data.get('valor_pago')))
        conn.commit()
        return jsonify({'id': cursor.lastrowid}), 201

if __name__ == '__main__':
    init_db()
    print("🚀 Servidor Python rodando em: http://localhost:3000")
    app.run(port=3000, debug=True)
