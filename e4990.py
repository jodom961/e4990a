#!/usr/bin/env python3

import argparse
import configparser
import datetime
import functools
import os
import sys
import time

import matplotlib.pyplot as pyplot
import numpy
import scipy.io as scio
import visa

fileext = '.mat'


def to_int(s):
    return int(float(s.strip()))


def main(filename):
    parser = configparser.ConfigParser()
    parser.read('e4990.ini')
    sweep_section = parser['sweep']
    start_frequency = to_int(sweep_section.get('start_frequency'))
    stop_frequency = to_int(sweep_section.get('stop_frequency'))
    number_of_points = to_int(sweep_section.get('number_of_points'))
    number_of_averages = to_int(sweep_section.get('number_of_averages'))
    oscillator_voltage = float(sweep_section.get('oscillator_voltage'))
    bias_voltage = to_int(sweep_section.get('bias_voltage'))
    number_of_intervals = to_int(sweep_section.get('number_of_intervals'))
    interval_period = float(sweep_section.get('interval_period'))

    rm = visa.ResourceManager()
    resources = rm.list_resources('USB?*INSTR')
    if not resources:
        print("No USB instruments found")
        return 1
    elif len(resources) > 1:
        print("Multiple USB instruments found:")
        for r in resources:
            print('\t' + r)
        return 1

    inst = rm.open_resource(resources[0])
    inst.timeout = 15000
    idn = inst.query(r'*IDN?').strip()
    print(idn)

    #inst.write('*RST')
    inst.write('*CLS')
    #inst.write(':SENS1:CORR1:STAT ON')
    #inst.write(':SENS1:CORR2:OPEN ON')
    #inst.write(':SENS1:CORR2:SHOR ON')
    #inst.write(':SENS1:CORR2:LOAD ON')
    def print_status(st):
        return "ON" if st else "OFF" 

    user_cal_status = to_int(inst.query(':SENS1:CORR1:STAT?'))
    print(f"User calibration status: {print_status(user_cal_status)}")
    open_cmp_status = to_int(inst.query(':SENS1:CORR2:OPEN?'))
    print(f"Open fixture compensation status: {print_status(open_cmp_status)}")
    short_cmp_status = to_int(inst.query(':SENS1:CORR2:SHOR?'))
    print(f"Short fixture compensation status: {print_status(short_cmp_status)}")
    load_cmp_status = to_int(inst.query(':SENS1:CORR2:LOAD?'))
    print(f"Load fixture compensation status: {print_status(load_cmp_status)}")
    
    inst.write(':CALC1:PAR1:DEF R')
    inst.write(':CALC1:PAR2:DEF X')
    inst.write(f':SENS1:SWE:POIN {number_of_points}')
    inst.write(f':SENS1:FREQ:START {start_frequency}')
    inst.write(f':SENS1:FREQ:STOP {stop_frequency}')

    inst.write(':CALC1:AVER ON')
    inst.write(f':CALC1:AVER:COUN {number_of_averages}')

    inst.write(':SOUR1:MODE VOLT')
    inst.write(f':SOUR1:VOLT {oscillator_voltage}')
    inst.write(':SOUR1:BIAS:MODE VOLT')
    inst.write(f':SOUR1:BIAS:VOLT {bias_voltage}')
    inst.write(':SOUR:BIAS:STAT ON')

    inst.write(':INIT1:CONT ON')
    inst.write(':TRIG:SOUR BUS')

    pyy = None
    ydims = number_of_points, number_of_intervals
    yx = numpy.zeros(ydims, dtype=numpy.float32)
    yr = numpy.zeros(ydims, dtype=numpy.float32)
    start_time = time.time()
    for i in range(0, number_of_intervals):
        inst.write('*CLS')
        inst.write(':DISP:WIND1:TRAC1:STAT OFF')
        inst.write(':DISP:WIND1:TRAC2:STAT OFF')
        acq_start_time = time.time()
        inst.write(':TRIG:SING')
        inst.query('*OPC?')
        acq_end_time = time.time() - acq_start_time
        print(f"Acquisition time is {acq_end_time:.2f} s")

        inst.write(':DISP:WIND1:TRAC1:STAT ON')
        inst.write(':DISP:WIND1:TRAC2:STAT ON')
        inst.write(':DISP:WIND1:TRAC1:Y:AUTO')
        inst.write(':DISP:WIND1:TRAC2:Y:AUTO')

        rlev1 = to_int(inst.query(':DISP:WIND1:TRAC1:Y:RLEV?'))
        rlev2 = to_int(inst.query(':DISP:WIND1:TRAC2:Y:RLEV?'))
        ndiv = to_int(inst.query(':DISP:WIND1:Y:DIV?'))
        pdiv1 = to_int(inst.query(':DISP:WIND1:TRAC1:Y:PDIV?'))
        pdiv2 = to_int(inst.query(':DISP:WIND1:TRAC2:Y:PDIV?'))
        ylim1 = rlev1 - ndiv / 2 * pdiv1, rlev1 + ndiv / 2 * pdiv1
        ylim2 = rlev2 - ndiv / 2 * pdiv2, rlev2 + ndiv / 2 * pdiv2

        query = functools.partial(inst.query_ascii_values, separator=',', 
                                container=numpy.ndarray)

        x = query(':SENS1:FREQ:DATA?')
        y = query(':CALC1:DATA:RDAT?')
        yx[:,i] = y[::2]
        yr[:,i] = y[1::2]
        if not pyy:
            pyy = PlotYY(x, ylim1, ylim2)
        pyy.update(yx[:,i], yr[:,i])

        sleep_time = interval_period * (i + 1) - (time.time() - start_time)
        if sleep_time < 0:
            print("The interval_period is too short")
            return 1
        print(f"Sleeping for {sleep_time:.2f} s")
        time.sleep(sleep_time)

    scio.savemat(filename, {
        'time': datetime.datetime.now().isoformat(),
        'idn': idn,
        'biasVoltage': bias_voltage,
        'oscillatorVoltage': oscillator_voltage,
        'numberOfAverages': number_of_averages,
        'userCalStatus': user_cal_status,
        'openCmpStatus': open_cmp_status,
        'shortCmpStatus': short_cmp_status,
        'loadCmpStatus': load_cmp_status,
        'Frequency': (start_frequency, stop_frequency),
        'X': yr,
        'R': yx,
    })
    print(f"Data saved to {filename}")

    inst.write(':SOUR:BIAS:STAT OFF')
    inst.close()
    rm.close()

    input("Press [ENTER] to exit\n")
    return 0


def default_filename():
    """Create ISO8601 timestamp as default filename

    The format is: YYYYMMDDTHHMMSS
    """
    now = datetime.datetime.now().isoformat()
    return now.replace('-', '').replace(':', '').split('.')[0]


class PlotYY:

    def __init__(self, t, y1lim, y2lim):
        self._t = t / 1e3  # Hz -> kHz
        self._fig, self._ax1 = pyplot.subplots()
        self._color1 = 'tab:orange'
        self._ax1.set_xlabel('Frequency [kHz]')
        self._ax1.set_ylabel('R', color=self._color1)
        self._ax1.set_xlim(self._t[0], self._t[-1])
        self._ax1.set_ylim(y1lim)
        self._ax1.tick_params(axis='y', labelcolor=self._color1)

        self._ax2 = self._ax1.twinx()  # instantiate a second axes that shares the same x-axis
        
        self._color2 = 'tab:blue'
        self._ax2.set_ylabel('X', color=self._color2)
        self._ax2.set_xlim(self._t[0], self._t[-1])
        self._ax2.set_ylim(y2lim)
        self._ax2.tick_params(axis='y', labelcolor=self._color2)
        self._lines1 = self._lines2 = None

        self._fig.tight_layout()  # otherwise the right y-label is slightly clipped
        pyplot.ion()
        pyplot.show()

    def update(self, y1, y2):
        if not self._lines1:
            self._lines1 = self._ax1.plot(self._t, y1, color=self._color1)
        else:
            self._lines1[0].set_ydata(y1)
        if not self._lines2:
            self._lines2 = self._ax2.plot(self._t, y2, color=self._color2)
        else:
            self._lines2[0].set_ydata(y2)
        pyplot.draw()
        pyplot.pause(0.001)


if __name__ == '__main__':
    default = default_filename()
    parser = argparse.ArgumentParser(description='E4990A acquisition script')
    parser.add_argument('filename', nargs='?')
    args = parser.parse_args()
    if args.filename:
        filename = args.filename
    else:
        filename = input(f"Enter a filepath or press [ENTER] to accept the "
                         f"default ({default}.mat):") or default
    if not filename.endswith(fileext):
        filename += fileext
    if os.path.exists(filename):
        resp = input(f"File {filename} exists. Are you sure you want "
                     f"to overwrite it (y/n)?")
        if resp.lower() != 'y':
            sys.exit(0)
    main(filename)

