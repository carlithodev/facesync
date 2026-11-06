"""
Text normalization helpers for the local conversational layer.

This module does not call AI services. It produces a matching-friendly
representation while preserving the original text for names and paths.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass(frozen=True)
class NormalizedToken:
    raw: str
    clean: str
    norm: str


@dataclass(frozen=True)
class NormalizedText:
    original: str
    clean_original: str
    ascii_text: str
    normalized: str
    tokens: List[str] = field(default_factory=list)
    token_items: List[NormalizedToken] = field(default_factory=list)
    corrections: Dict[str, str] = field(default_factory=dict)

    def has(self, word: str) -> bool:
        return TextNormalizer.strip_accents(word).lower() in set(self.tokens)

    def has_any(self, words) -> bool:
        token_set = set(self.tokens)
        return any(TextNormalizer.strip_accents(str(word)).lower() in token_set for word in words)

    def contains_phrase(self, phrase: str) -> bool:
        phrase_norm = TextNormalizer.normalize_for_matching(phrase)
        return phrase_norm in self.normalized


class TextNormalizer:
    """
    Normalizes Spanish user text for local intent matching.

    The corrected/normalized text is only for comparison. Slot extraction keeps
    names from the original tokens so a folder named "Ian" stays "Ian".
    """

    COMMON_CORRECTIONS: Dict[str, str] = {
        "caeprta": "carpeta",
        "karpeta": "carpeta",
        "capeta": "carpeta",
        "carpetita": "carpeta",
        "folder": "carpeta",
        "directorio": "carpeta",
        "folders": "carpetas",
        "directorios": "carpetas",
        "almuno": "alumno",
        "almunos": "alumnos",
        "alumos": "alumnos",
        "alumo": "alumno",
        "alunos": "alumnos",
        "estudiante": "alumno",
        "estudiantes": "alumnos",
        "ecxel": "excel",
        "exel": "excel",
        "xlsx": "excel",
        "xls": "excel",
        "lista": "excel",
        "refecia": "referencia",
        "referncia": "referencia",
        "referencia": "referencia",
        "nuemero": "numero",
        "numero": "numero",
        "num": "numero",
        "no": "numero",
        "idetifica": "identifica",
        "indentifica": "identifica",
        "reconoce": "identifica",
        "reconoser": "reconocer",
        "reconocer": "reconocer",
        "archio": "archivo",
        "arhcivo": "archivo",
        "documento": "archivo",
        "fots": "fotos",
        "foto": "foto",
        "fotosss": "fotos",
        "imajen": "imagen",
        "imagenes": "imagenes",
        "imagen": "imagen",
        "fotografia": "foto",
        "fotografias": "fotos",
        "fotograf?a": "foto",
        "fotograf?as": "fotos",
        "imágenes": "imagenes",
        "mete": "meter",
        "metelas": "meter",
        "metelos": "meter",
        "guarda": "guardar",
        "guardalas": "guardar",
        "guardalos": "guardar",
        "guardarles": "guardar",
        "quita": "quitar",
        "pon": "poner",
        "ponme": "poner",
        "ponle": "poner",
        "manda": "mandar",
        "mandalas": "mandar",
        "mandalos": "mandar",
        "mandar": "mandar",
        "pasa": "mover",
        "pasame": "mover",
        "toma": "tomar",
        "tomar": "tomar",
        "muevelo": "mueve",
        "muevela": "mueve",
        "copia": "copiar",
        "copialos": "copiar",
        "copialas": "copiar",
        "acomoda": "organizar",
        "acomodalas": "organizar",
        "acomodalos": "organizar",
        "separa": "clasificar",
        "separalas": "clasificar",
        "separalos": "clasificar",
        "clasifica": "clasificar",
        "clasificalas": "clasificar",
        "clasificalos": "clasificar",
        "organiza": "organizar",
        "organizalas": "organizar",
        "organizalos": "organizar",
        "ordena": "organizar",
        "ordenalas": "organizar",
        "ordenalos": "organizar",
        "basandote": "basandote",
        "basate": "basandote",
        "basado": "basado",
        "tomando": "tomando",
        "creaame": "creame",
        "creame": "creame",
        "cr?ame": "creame",
        "hazme": "haz",
        "hacer": "haz",
        "generame": "genera",
        "genera": "genera",
        "prepara": "preparar",
        "preparame": "preparar",
        "ensename": "muestra",
        "muestrame": "muestra",
        "mu?strame": "muestra",
        "llama": "llamada",
        "llamalo": "renombralo",
        "llamala": "renombrala",
        "llamados": "llamado",
        "llamadas": "llamada",
        "necesito": "necesitar",
        "necesita": "necesitar",
        "ocupo": "necesitar",
        "ocupa": "necesitar",
        "saca": "extraer",
        "sacar": "extraer",
        "van": "van",
        "ban": "van",
        "alli": "alli",
        "ahi": "ahi",
        "aqui": "aqui",
        "aca": "aca",
        "ahí": "ahi",
        "aquí": "aqui",
        "acá": "aca",
        "ah?": "ahi",
        "ah": "ahi",
        "allí": "alli",
        "sal?n": "salon",
        "salón": "salon",
        "múltiples": "multiples",
        "multiples": "multiples",
        "ren?mbrala": "renombrala",
        "ren?mbralo": "renombralo",
    }

    CONNECTORS = {
        "llamada",
        "llamado",
        "que se llame",
        "que se nombre",
        "con nombre",
        "con el nombre",
        "para",
        "de",
        "dentro de",
        "adentro de",
        "en la carpeta",
        "donde estoy",
        "ahi",
        "alli",
    }

    TOKEN_RE = re.compile(r"[^\s,;:!()\"'`]+", re.UNICODE)

    @staticmethod
    def strip_accents(value: str) -> str:
        text = unicodedata.normalize("NFKD", str(value or ""))
        return "".join(ch for ch in text if not unicodedata.combining(ch))

    @classmethod
    def normalize_for_matching(cls, value: str) -> str:
        text = cls.strip_accents(value).lower()
        text = re.sub(r"[^\w.\-/\\]+", " ", text, flags=re.UNICODE)
        text = re.sub(r"\s+", " ", text).strip()
        parts = [cls.COMMON_CORRECTIONS.get(part, part) for part in text.split()]
        return " ".join(parts)

    @classmethod
    def normalize_token(cls, token: str) -> str:
        clean = str(token or "").strip().strip(".,;:!?()[]{}\"'`")
        base = cls.strip_accents(clean).lower()
        return cls.COMMON_CORRECTIONS.get(base, base)

    @classmethod
    def normalize(cls, text: str) -> NormalizedText:
        clean_original = re.sub(r"\s+", " ", str(text or "")).strip()
        ascii_text = cls.strip_accents(clean_original).lower()
        ascii_text = re.sub(r"\s+", " ", ascii_text).strip()

        token_items: List[NormalizedToken] = []
        corrections: Dict[str, str] = {}

        for match in cls.TOKEN_RE.finditer(clean_original):
            raw = match.group(0)
            clean = raw.strip().strip(".,;:!?()[]{}\"'`")
            if not clean:
                continue
            before = cls.strip_accents(clean).lower()
            after = cls.COMMON_CORRECTIONS.get(before, before)
            if before != after:
                corrections[clean] = after
            token_items.append(NormalizedToken(raw=raw, clean=clean, norm=after))

        tokens = [item.norm for item in token_items]
        normalized = " ".join(tokens)
        normalized = re.sub(r"\s+", " ", normalized).strip()

        return NormalizedText(
            original=str(text or ""),
            clean_original=clean_original,
            ascii_text=ascii_text,
            normalized=normalized,
            tokens=tokens,
            token_items=token_items,
            corrections=corrections,
        )
