"""Tests de la préparation du texte (sans GPU ni modèle).
Lancer : build\\runtime\\python\\python.exe -m unittest server.tests.test_speech_text -v   (depuis la racine du projet)

Chaque cas vient d'un défaut mesuré en retranscrivant l'audio avec Whisper (voir server/speech_text.py)."""
import unittest

from server import speech_text as st

# Caractères que le tokenizer XTTS ne connaît pas (mesuré sur vos livres) — simulé ici sans charger le modèle
UNKNOWN = set("©[]+}ǐ")
known = lambda ch: ch not in UNKNOWN   # noqa: E731


def chunks(text, is_known=known):
    return st.chunk_text(text, is_known)


class Nettoyage(unittest.TestCase):
    def test_guillemets_supprimes(self):
        self.assertEqual(st.clean_for_speech("Il dit : « Je pars. »"), "Il dit: Je pars.")
        self.assertEqual(st.clean_for_speech("He said, “Go.”"), "He said, Go.")

    def test_apostrophe_typographique_gardee_entre_lettres(self):
        self.assertEqual(st.clean_for_speech("Il n’a rien dit"), "Il n'a rien dit")
        self.assertEqual(st.clean_for_speech("‘Yes,’ he said."), "Yes, he said.")

    def test_appels_de_note(self):
        self.assertEqual(st.clean_for_speech("The results [1] are known [2, 3] and [4–6] clear."), "The results are known and clear.")
        self.assertEqual(st.clean_for_speech("Humans are animals.1 The next idea."), "Humans are animals. The next idea.")
        self.assertEqual(st.clean_for_speech("Des animaux.¹ Suite."), "Des animaux. Suite.")

    def test_nombres_legitimes_conserves(self):
        self.assertEqual(st.clean_for_speech("The ratio was 3.5 to one."), "The ratio was 3.5 to one.")
        self.assertEqual(st.clean_for_speech("See p.12 for details."), "See page 12 for details.")   # pas pris pour une note de bas de page
        self.assertEqual(st.clean_for_speech("In 1945. The war ended."), "In 1945. The war ended.")

    def test_symboles_et_caracteres_inconnus(self):
        self.assertEqual(st.clean_for_speech("Copyright © 2020 Example Press.", known), "Copyright 2020 Example Press.")
        self.assertEqual(st.clean_for_speech("a + b", known), "a plus b")
        self.assertEqual(st.clean_for_speech("fiﬁn­​"), "fifin")

    def test_abreviations_dites_en_toutes_lettres(self):
        self.assertEqual(st.clean_for_speech("See p. 12 and pp. 14-16.", None, "en"), "See page 12 and pages 14-16.")
        self.assertEqual(st.clean_for_speech("Question No. 5", None, "en"), "Question number 5")
        self.assertEqual(st.clean_for_speech("Voir p. 12 et n° 3.", None, "fr"), "Voir page 12 et numéro 3.")
        self.assertEqual(st.clean_for_speech("See p. A and the map.", None, "en"), "See p. A and the map.")   # pas de nombre : inchangé

    def test_espaces_insecables(self):
        self.assertEqual(st.clean_for_speech("Quoi ? Oui !"), "Quoi? Oui!")

    def test_points_de_suspension(self):
        self.assertEqual(st.clean_for_speech("Il attendit . . . puis partit"), "Il attendit... puis partit")
        self.assertEqual(st.clean_for_speech("Il hésita…"), "Il hésita...")


class Decoupage(unittest.TestCase):
    def test_jamais_de_morceau_de_ponctuation_seule(self):
        # Cas réel : l'espace avant le guillemet fermant faisait un morceau « ” » lu comme du charabia
        for text in ("He said, “Go away, I will not listen to you anymore. ”", "Il dit : « Va-t’en, je ne veux plus rien entendre de toi. »"):
            out = chunks(text)
            self.assertEqual(len(out), 1, out)
            self.assertTrue(all(any(c.isalnum() for c in x) for x in out))

    def test_texte_sans_rien_a_dire(self):
        for text in (".", "”", "»", "©", "[1]", "  ", "* * *", "…"):
            self.assertEqual(chunks(text), [], text)

    def test_abreviations_ne_coupent_pas(self):
        self.assertEqual(chunks("The committee approved the plan (see p. 12)."), ["The committee approved the plan (see page 12)."])
        self.assertEqual(chunks("It was the answer to question No. 5."), ["It was the answer to question number 5."])
        self.assertEqual(chunks("Mr. Smith met Dr. Jones at St. Paul's church in the morning."), ["Mr. Smith met Dr. Jones at St. Paul's church in the morning."])
        self.assertEqual(chunks("J. K. Rowling wrote the book and it was a great success."), ["J. K. Rowling wrote the book and it was a great success."])

    def test_vraie_fin_de_phrase_coupe(self):
        text = "The sun rose over the hills and the whole valley woke up. The village was still asleep and nobody had lit a fire yet."
        self.assertEqual(len(chunks(text)), 2)

    def test_etc_en_fin_de_phrase(self):
        out = chunks("They sold apples, pears, plums and many other kinds of fruit, etc. The market closed at noon on that day.")
        self.assertEqual(len(out), 2)
        self.assertTrue(out[0].endswith("etc."))

    def test_suite_en_minuscule_n_est_pas_une_fin_de_phrase(self):
        out = chunks("He bought apples, pears, etc. and left the shop quickly because it was late in the evening already.")
        self.assertEqual(len(out), 1)

    def test_dernier_morceau_jamais_orphelin(self):
        long_sentence = "It was a bright cold day in April, and the clocks were striking thirteen across the whole city."
        out = chunks(long_sentence + " Yes.")
        self.assertEqual(len(out), 1, out)
        self.assertTrue(out[0].endswith("Yes."))

    def test_titre_court_garde(self):
        self.assertEqual(chunks("Chapter 1"), ["Chapter 1."])
        self.assertEqual(chunks("Introduction"), ["Introduction."])

    def test_fin_de_morceau_toujours_ponctuee(self):
        self.assertEqual(chunks("He listed three reasons:"), ["He listed three reasons."])
        self.assertEqual(chunks("He waited for an answer—"), ["He waited for an answer."])
        self.assertEqual(chunks("What do you think?"), ["What do you think?"])
        self.assertEqual(chunks("She smiled (as she always did)"), ["She smiled (as she always did)."])

    def test_taille_maximale(self):
        text = " ".join(["This is a fairly long sentence that keeps going on and on without any stop"] * 8) + "."
        for c in chunks(text):
            self.assertLessEqual(len(c), st.HARD_LIMIT)


if __name__ == "__main__":
    unittest.main()
