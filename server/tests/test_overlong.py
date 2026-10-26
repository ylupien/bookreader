"""Détection des morceaux anormalement longs (mot parasite, charabia) : logique pure, sans modèle ni GPU.
Lancer : build\\runtime\\python\\python.exe -m unittest server.tests.test_overlong -v   (depuis la racine du projet)"""
import collections
import unittest

from server import tts_engine as te

KEY = ("fr", 1.0)
CHUNK = "x" * 100   # 100 caractères


class Overlong(unittest.TestCase):
    def setUp(self):
        te._rates.clear()

    def test_sans_calibration_seuil_large(self):
        # 15 caractères/s par défaut : 100 caractères ≈ 6,7 s ; suspect au-delà de 10 s
        self.assertFalse(te.is_overlong(CHUNK, 9.0, KEY))
        self.assertTrue(te.is_overlong(CHUNK, 11.0, KEY))

    def test_avec_calibration_de_la_voix(self):
        te._rates[KEY] = collections.deque([20.0] * 6)   # voix rapide : 100 caractères ≈ 5 s ; suspect au-delà de 7,5 s
        self.assertFalse(te.is_overlong(CHUNK, 7.0, KEY))
        self.assertTrue(te.is_overlong(CHUNK, 8.5, KEY))

    def test_calibration_ignoree_si_trop_peu_de_morceaux(self):
        te._rates[KEY] = collections.deque([40.0] * 2)   # 2 < CALIBRATION_MIN : on garde la valeur par défaut
        self.assertFalse(te.is_overlong(CHUNK, 9.0, KEY))

    def test_morceau_court(self):
        short = "x" * 10                                # ≈ 0,7 s attendue
        self.assertTrue(te.is_overlong(short, 2.5, KEY))     # +1,8 s et plus de 1,5× : mot parasite
        self.assertFalse(te.is_overlong(short, 1.7, KEY))    # +1,0 s seulement : variation normale

    def test_nombres_non_comparables(self):
        self.assertFalse(te.is_overlong("En 1945 puis 1946 et 2020", 20.0, KEY))

    def test_cles_independantes_par_langue_et_vitesse(self):
        te._rates[("fr", 1.0)] = collections.deque([20.0] * 6)
        self.assertTrue(te.is_overlong(CHUNK, 8.5, ("fr", 1.0)))
        self.assertFalse(te.is_overlong(CHUNK, 8.5, ("en", 1.0)))   # pas de calibration pour « en » : seuil large


if __name__ == "__main__":
    unittest.main()
