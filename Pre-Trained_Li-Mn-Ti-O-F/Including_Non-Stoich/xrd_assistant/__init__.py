import matplotlib.pyplot as plt
import keras
import keras.backend as K
from scipy.signal import find_peaks
from dtw import dtw, warp
from scipy.signal import lfilter
import random
import pymatgen as mg
from pymatgen.analysis.diffraction import xrd
import cv2
from cv2_rolling_ball import subtract_background_rolling_ball
import tensorflow as tf
from tensorflow.python.keras.backend import eager_learning_phase_scope
from scipy import interpolate as ip
import ast
import numpy as np
import os


def explore_mixtures(spectrum, kdp, reference_phases):
    total_confidence, all_predictions = [], []
    tabulate_conf, predicted_cmpd_set = [], []
    measured_spectrum = prepare_pattern(spectrum) ## Clean up measured spectrum
    prediction_1, num_phases_1, certanties_1 = kdp.predict(measured_spectrum) ## Return predicted vector, number of probable phases (confidence > 10%), and associated confidence values
    for i1 in range(num_phases_1): ## Consider all probable phases as a possible first phase
        tabulate_conf.append(certanties_1[i1])
        phase_index = np.array(prediction_1).argsort()[-(i1+1)] ## Get index of 1st, 2nd, etc. most probable phase depending on i1
        predicted_cmpd = reference_phases[phase_index] ## Get predicted compound associated with probable phase defined above
        predicted_cmpd_set.append(predicted_cmpd)
        stripped_y_1, norm_1 = get_reduced_pattern(predicted_cmpd, measured_spectrum) ## Strips away predicted phase from original spectrum
        if stripped_y_1 == 'All phases identified':
            total_confidence.append(sum(tabulate_conf)/len(tabulate_conf))
            all_predictions.append(predicted_cmpd_set)
            tabulate_conf, predicted_cmpd_set = [], []
        else:
            prediction_2, num_phases_2, certanties_2 = kdp.predict([[val] for val in stripped_y_1])
            for i2 in range(num_phases_2):
                phase_index = np.array(prediction_2).argsort()[-(i2+1)]
                predicted_cmpd = reference_phases[phase_index]
                if predicted_cmpd in predicted_cmpd_set: ## If we've already predicted this compound, go to next most probable
                    all_predictions.append(predicted_cmpd_set) ## Only include first identified phase
                    total_confidence.append(sum(tabulate_conf)/len(tabulate_conf)) ## Confidence associated with first phase
                    if i2 == (num_phases_2 - 1):
                        tabulate_conf, predicted_cmpd_set = [], [] ## If we're out of phases, then restart (move on to next branch)
                    continue
                else: ## If 2nd phase is new (different from 1st phase)
                    tabulate_conf.append(certanties_2[i2])
                    predicted_cmpd_set.append(predicted_cmpd)
                stripped_y_2, norm_2 = get_reduced_pattern(predicted_cmpd, stripped_y_1, norm_1) ## Strips away predicted phase from original spectrum
                if stripped_y_2 == 'All phases identified':
                    total_confidence.append(sum(tabulate_conf)/len(tabulate_conf))
                    all_predictions.append(predicted_cmpd_set)
                    if i2 == (num_phases_2 - 1):
                        tabulate_conf, predicted_cmpd_set = [], []
                    else:
                        tabulate_conf, predicted_cmpd_set = tabulate_conf[:-1], predicted_cmpd_set[:-1]
                else:
                    prediction_3, num_phases_3, certanties_3 = kdp.predict([[val] for val in stripped_y_2])
                    for i3 in range(num_phases_3):
                        phase_index = np.array(prediction_3).argsort()[-(i3+1)]
                        predicted_cmpd = reference_phases[phase_index]
                        if predicted_cmpd in predicted_cmpd_set: ## If we've already predicted this compound, go to next most probable
                            all_predictions.append(predicted_cmpd_set) ## Only include 1st and 2nd phases
                            total_confidence.append(sum(tabulate_conf)/len(tabulate_conf)) ## Confidence associated with 1st and 2nd phases
                            ## Removed re-setting of tabulated stuff...I think this is the right move, but need to double-check
                            continue
                        else: ## If 3rd phase is new (different from 1st and 2st phases)
                            tabulate_conf.append(certanties_3[i3])
                            predicted_cmpd_set.append(predicted_cmpd)
                            all_predictions.append(predicted_cmpd_set) ## First, second phase, and third phase
                            total_confidence.append(sum(tabulate_conf)/len(tabulate_conf)) ## Average confidence associated with all phases
                            tabulate_conf = tabulate_conf[:-1] ## Remove third phase before moving onto next
                            predicted_cmpd_set = predicted_cmpd_set[:-1] ## Remove third phase confidence before moving onto next

    return all_predictions, total_confidence


def get_reduced_pattern(predicted_cmpd, orig_y, last_normalization=1.0):
    pred_y = generate_pattern(predicted_cmpd)
    dtw_info = dtw(pred_y, orig_y, window_type="slantedband", window_args={'window_size': 20}) ## corresponds to about 1.5 degree shift
    warp_indices = warp(dtw_info)
    warped_spectrum = list(pred_y[warp_indices])
    warped_spectrum.append(0.0)
    warped_spectrum = scale_spectrum(warped_spectrum, orig_y)
    stripped_y = strip_spectrum(warped_spectrum, orig_y)
    stripped_y = smooth_spectrum(stripped_y)
    stripped_y = np.array(stripped_y) - min(stripped_y)
    if max(stripped_y) >= (10*last_normalization):
        new_normalization = 100/max(stripped_y)
        stripped_y = new_normalization*stripped_y
        return stripped_y, new_normalization
    else:
        return 'All phases identified', None


def prepare_pattern(spectrum_name, smooth=True):

    data = np.loadtxt(spectrum_name)
    x = data[:, 0]
    y = data[:, 1]

    f = ip.CubicSpline(x, y)
    xs = np.linspace(10, 80, 4501)
    ys = f(xs)


    n = 20  # the larger n is, the smoother curve will be
    b = [1.0 / n] * n
    a = 1
    yy = lfilter(b, a, ys)
    ys = yy
    ys[0:21] = [ys[21]]*21

    ys = [val - min(ys) for val in ys]
    ys = [255*(val/max(ys)) for val in ys]
    ys = [int(val) for val in ys]

    pixels = []
    for q in range(10):
        pixels.append(ys)
    pixels = np.array(pixels)
    img, background = subtract_background_rolling_ball(pixels, 800, light_background=False,
                                         use_paraboloid=True, do_presmooth=False)
    yb = np.array(background[0])
    ys = np.array(ys) - yb

    ys = np.array(ys) - min(ys)
    ys = list(100*np.array(ys)/max(ys))

    return ys

def generate_pattern(cmpd, scale_vol=1.0, std_dev=0.15, max_I=100.0):

    try:
        struct = mg.Structure.from_file('Stoich_Refs/%s' % cmpd)
    except FileNotFoundError:
        struct = mg.Structure.from_file('Non-Stoich_Refs/%s' % cmpd)
    equil_vol = struct.volume
    struct.scale_lattice(scale_vol * equil_vol)
    calculator = xrd.XRDCalculator()
    pattern = calculator.get_pattern(struct, two_theta_range=(10,80))
    angles = pattern.x
    peaks = pattern.y

    x = np.linspace(10, 80, 4501)
    y = []
    for val in x:
        ysum = 0
        for (ang, pk) in zip(angles, peaks):
            if np.isclose(ang, val, atol=0.05):
                ysum += pk
        y.append(ysum)
    conv = []
    for (ang, int) in zip(x, y):
        if int != 0:
            gauss = [int*np.exp((-(val - ang)**2)/std_dev) for val in x]
            conv.append(gauss)
    mixed_data = zip(*conv)
    all_I = []
    for values in mixed_data:
        all_I.append(sum(values))

    all_I = np.array(all_I) - min(all_I)
    all_I = 100*all_I/max(all_I)

    return all_I


class KerasDropoutPrediction(object):

    def __init__(self, model):
        self.f = tf.keras.backend.function(model.layers[0].input, model.layers[-1].output)

    def predict(self, x, n_iter=1000):
        x = [[val] for val in x]
        x = np.array([x])
        result = []
        with eager_learning_phase_scope(value=1):
            for _ in range(n_iter):
                result.append(self.f(x))

        result = np.array([list(np.array(sublist).flatten()) for sublist in result]) ## Individual predictions
        prediction = result.mean(axis=0) ## Average prediction

        all_preds = [np.argmax(pred) for pred in result] ## Individual max indices (associated with phases)

        counts = []
        for index in set(all_preds):
            counts.append(all_preds.count(index)) ## Tabulate how many times each prediction arises

        certanties = []
        for each_count in counts:
            conf = each_count/sum(counts)
            if conf >= 0.1: ## If prediction occurs at least 10% of the time
                certanties.append(conf)
        certanties = sorted(certanties, reverse=True)

        return prediction, len(certanties), certanties


def smooth_spectrum(warped_spectrum):
    n = 20  # the larger n is, the smoother curve will be
    b = [1.0 / n] * n
    a = 1
    yy = lfilter(b, a, warped_spectrum)
    ys = yy
    shifted_ys = []
    for val in ys[11:]:
        shifted_ys.append(val)
    for z in range(11):
        shifted_ys.append(0.0)
    warped_spectrum = shifted_ys
    return warped_spectrum

def scale_spectrum(warped_spectrum, orig_y):
    orig_peaks = find_peaks(orig_y, height=5)[0] ## list of peak indices
    pred_peaks = find_peaks(warped_spectrum, height=5)[0] ## list of peak indices
    matched_orig_peaks = []
    matched_pred_peaks = []
    for a in orig_peaks:
        for b in pred_peaks:
            if np.isclose(a, b, atol=50): ## within 50 indices of one another
                matched_orig_peaks.append(a)
                matched_pred_peaks.append(b)
    num_match = []
    for scale_spectrum in np.linspace(1.2, 0.2, 101):
        check = scale_spectrum*np.array(warped_spectrum)
        good_peaks = 0
        for (a, b) in zip(matched_orig_peaks, matched_pred_peaks):
            A_magnitude = orig_y[a]
            B_magnitude = check[b]
            if abs((A_magnitude - B_magnitude)/A_magnitude) < 0.1: ## If peaks are within 10% of one another
                good_peaks += 1
        num_match.append(good_peaks)
    best_scale = np.linspace(1.2, 0.2, 101)[np.argmax(num_match)] ## Will give highest scaling constant which yields best match
    warped_spectrum = best_scale*np.array(warped_spectrum) ## Scale
    return warped_spectrum

def strip_spectrum(warped_spectrum, orig_y):
    stripped_y = orig_y - warped_spectrum
    fixed_y = []
    for val in stripped_y:
        if val < 0:
            fixed_y.append(0.0)
        else:
            fixed_y.append(val)
    stripped_y = fixed_y
    return stripped_y

def plot_spectra(warped_spectrum, stripped_y, orig_y):
    x = np.linspace(10, 80, 4501)
    plt.figure()
    plt.plot(x, orig_y[-1], 'b-')
    plt.plot(x, warped_spectrum, 'r-')
    plt.plot(x, stripped_y, 'g-')
    plt.show()

