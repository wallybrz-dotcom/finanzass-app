from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, Float, String, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from typing import List, Optional
from datetime import datetime

# --- BASE DE DATOS ---
DATABASE_URL = "sqlite:///./finanzas.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class TransaccionDB(Base):
    __tablename__ = "transacciones"
    id = Column(Integer, primary_key=True, index=True)
    monto = Column(Float, nullable=False)
    categoria = Column(String, nullable=False)
    es_fijo = Column(Boolean, default=False)
    mes = Column(Integer, nullable=False)
    anio = Column(Integer, nullable=False)

class MetaAhorroDB(Base):
    __tablename__ = "metas_ahorro"
    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String, nullable=False)
    monto_objetivo = Column(Float, nullable=False)
    monto_actual = Column(Float, default=0.0)

class PresupuestoDB(Base):
    __tablename__ = "presupuestos"
    id = Column(Integer, primary_key=True, index=True)
    categoria = Column(String, nullable=False, unique=True)
    monto_maximo = Column(Float, nullable=False)

Base.metadata.create_all(bind=engine)

# --- MODELOS PYDANTIC ---
class TransaccionCrear(BaseModel):
    monto: float
    categoria: str
    es_fijo: bool
    mes: Optional[int] = None
    anio: Optional[int] = None

class MetaCrear(BaseModel):
    nombre: str
    monto_objetivo: float

class MetaAportar(BaseModel):
    meta_id: int
    monto: float

class PresupuestoCrear(BaseModel):
    categoria: str
    monto_maximo: float

class EvaluacionCuota(BaseModel):
    precio_contado: float
    precio_cuotas_total: float
    cantidad_cuotas: int
    inflacion_mensual_estimada: float

app = FastAPI(title="Finanzas API - Sistema Completo")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- ENDPOINTS GASTOS Y BALANCE ---
@app.get("/")
def inicio():
    return {"mensaje": "API de Finanzas funcionando"}

@app.post("/agregar-gasto")
def agregar_gasto(transaccion: TransaccionCrear, db: Session = Depends(get_db)):
    ahora = datetime.now()
    mes_actual = transaccion.mes if transaccion.mes else ahora.month
    anio_actual = transaccion.anio if transaccion.anio else ahora.year

    nuevo = TransaccionDB(
        monto=transaccion.monto,
        categoria=transaccion.categoria.capitalize(),
        es_fijo=transaccion.es_fijo,
        mes=mes_actual,
        anio=anio_actual
    )
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return {"mensaje": "Gasto guardado", "registro": nuevo}

@app.get("/listar-gastos")
def listar_gastos(mes: int, anio: int, db: Session = Depends(get_db)):
    return db.query(TransaccionDB).filter(TransaccionDB.mes == mes, TransaccionDB.anio == anio).all()

@app.delete("/eliminar-gasto/{gasto_id}")
def eliminar_gasto(gasto_id: int, db: Session = Depends(get_db)):
    gasto = db.query(TransaccionDB).filter(TransaccionDB.id == gasto_id).first()
    if not gasto:
        raise HTTPException(status_code=404, detail="Gasto no encontrado")
    db.delete(gasto)
    db.commit()
    return {"mensaje": "Gasto eliminado"}

@app.get("/obtener-balance")
def obtener_balance(sueldo_mensual: float, mes: int, anio: int, db: Session = Depends(get_db)):
    transacciones = db.query(TransaccionDB).filter(TransaccionDB.mes == mes, TransaccionDB.anio == anio).all()
    gastos_fijos = sum(t.monto for t in transacciones if t.es_fijo)
    gastos_variables = sum(t.monto for t in transacciones if not t.es_fijo)
    total_gastos = gastos_fijos + gastos_variables
    disponible = sueldo_mensual - total_gastos

    por_categoria = {}
    for t in transacciones:
        por_categoria[t.categoria] = por_categoria.get(t.categoria, 0) + t.monto

    # Diagnóstico y Asesor Financiero
    consejos = []
    if sueldo_mensual > 0:
        pct_fijos = (gastos_fijos / sueldo_mensual) * 100
        if pct_fijos > 50:
            consejos.append(f"Tus gastos fijos equivalen al {round(pct_fijos, 1)}% de tus ingresos. Lo ideal es no superar el 50%. Revisa contratos o servicios no indispensables.")
        if disponible < 0:
            categoria_mayor = max(por_categoria, key=por_categoria.get) if por_categoria else None
            if categoria_mayor:
                consejos.append(f"Estás en déficit de ${abs(disponible)}. Tu mayor rubro de gasto es '{categoria_mayor}' (${por_categoria[categoria_mayor]}). Enfoca tus recortes ahí.")

    # Control de Presupuestos
    presupuestos_db = db.query(PresupuestoDB).all()
    alertas_presupuesto = []
    for p in presupuestos_db:
        gastado = por_categoria.get(p.categoria, 0)
        if gastado > p.monto_maximo:
            alertas_presupuesto.append(f"Superaste el límite para '{p.categoria}': Gastado ${gastado} / Límite ${p.monto_maximo}")

    return {
        "sueldo": sueldo_mensual,
        "gastos_fijos": gastos_fijos,
        "gastos_variables": gastos_variables,
        "total_gastos": total_gastos,
        "disponible_real": disponible,
        "porcentaje_gastado": round((total_gastos / sueldo_mensual) * 100, 2) if sueldo_mensual > 0 else 0,
        "desglose_categorias": por_categoria,
        "consejos": consejos,
        "alertas_presupuesto": alertas_presupuesto
    }

# --- PRESUPUESTOS POR CATEGORÍA ---
@app.post("/definir-presupuesto")
def definir_presupuesto(p: PresupuestoCrear, db: Session = Depends(get_db)):
    cat = p.categoria.capitalize()
    existente = db.query(PresupuestoDB).filter(PresupuestoDB.categoria == cat).first()
    if existente:
        existente.monto_maximo = p.monto_maximo
    else:
        nuevo = PresupuestoDB(categoria=cat, monto_maximo=p.monto_maximo)
        db.add(nuevo)
    db.commit()
    return {"mensaje": "Presupuesto configurado"}

# --- METAS DE AHORRO ---
@app.post("/crear-meta")
def crear_meta(meta: MetaCrear, db: Session = Depends(get_db)):
    nueva = MetaAhorroDB(nombre=meta.nombre, monto_objetivo=meta.monto_objetivo)
    db.add(nueva)
    db.commit()
    db.refresh(nueva)
    return {"mensaje": "Meta creada", "meta": nueva}

@app.get("/listar-metas")
def listar_metas(db: Session = Depends(get_db)):
    return db.query(MetaAhorroDB).all()

@app.post("/aportar-meta")
def aportar_meta(aporte: MetaAportar, db: Session = Depends(get_db)):
    meta = db.query(MetaAhorroDB).filter(MetaAhorroDB.id == aporte.meta_id).first()
    if not meta:
        raise HTTPException(status_code=404, detail="Meta no encontrada")
    meta.monto_actual += aporte.monto
    db.commit()
    return {"mensaje": "Aporte realizado", "monto_actual": meta.monto_actual}

# --- EVALUADOR DE CUOTAS ---
@app.post("/evaluar-cuotas")
def evaluar_cuotas(data: EvaluacionCuota):
    monto_cuota = data.precio_cuotas_total / data.cantidad_cuotas
    valor_presente = sum(
        monto_cuota / ((1 + data.inflacion_mensual_estimada) ** i)
        for i in range(1, data.cantidad_cuotas + 1)
    )
    conviene = valor_presente < data.precio_contado

    return {
        "monto_cuota_mensual": round(monto_cuota, 2),
        "veredicto": "Comprar en cuotas" if conviene else "Pagar de contado",
        "ahorro_estimado": round(data.precio_contado - valor_presente, 2) if conviene else 0
    }from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# Permitir solicitudes desde el celular y GitHub Pages
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
