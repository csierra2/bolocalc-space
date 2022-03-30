import sys
import os
src_path = os.path.join("..", "src")
if src_path not in sys.path:
    sys.path.append(src_path)
import unpack as up
import subprocess
import numpy as np
import pandas as pd

class GenBolos:
    
    def __init__(self,bc_fp,exp_fp,band_edges,eta=0.7):
        """ Accept a tuple of band edges, e.g. ([10,40], [40,80], ...) and write as tophats to the specified Bolocalc experiment directory with a default 0.7 detector efficiency"""
        self.bc_fp = bc_fp
        self.exp_fp = exp_fp
        self.band_edges = np.vstack(band_edges)
        self.N_bands = len(self.band_edges)
        self.freqs = np.arange(0.75*np.min(self.band_edges), 1.25*np.max(self.band_edges))
        self.passbands = np.zeros( (self.N_bands, self.freqs.shape[0]))
        for b,edges in enumerate(self.band_edges):
            for j,freq in enumerate(self.freqs):
                if freq > edges[0] and freq < edges[1]:
                    self.passbands[b,j] = 1
        self.passbands *= eta
        self.band_centers = np.sum( self.freqs * self.passbands, axis=1) / np.sum(self.passbands, axis=1)
        
        # generate pixel sizes [mm] by scaling lower band edges 
        self.norm_edge = 80  # expect 10 mm diameter pixels with low edge at 80 mm
        self.diff_edges = abs(self.band_edges[:,0] - self.norm_edge)
        self.idx = self.diff_edges.argmin()
        if self.diff_edges[self.idx] > 50:
            print('Warning: Pixel sizes may not be accurate with these edges')
        self.pixel_sizes = (10/2) * 2 * self.band_edges[self.idx,0]/self.band_edges[:,0]
        
        self.unpack = up.Unpack()
        self.unpack.unpack_sensitivities(self.exp_fp)
        for exp in self.unpack.sens_outputs.keys():
            if exp == 'Summary':
                continue
            self.exp = exp
            for tel in self.unpack.sens_outputs[exp].keys():
                if tel == 'Summary':
                    continue
                self.tel = tel
                for cam in self.unpack.sens_outputs[exp][tel].keys():
                    if cam == 'Summary':
                        continue
                    self.cam = cam
        self.cam_config = f'{self.exp_fp}{self.tel}/{self.cam}/config/'
        self.bands_fp = f'{self.cam_config}Bands/Detectors/'
        self.optics_fp = f'{self.cam_config}optics.txt'
        self.channels_fp = f'{self.cam_config}channels.txt'
        self.cmd_bolo = ['python3', self.bc_fp, self.exp_fp]
        
        self.optics_titles =     ("Element", "Temperature",
                "Absorption", "Reflection",
                "Thickness", "Index",
                "Loss Tangent", "Conductivity",
                "Surface Rough", "Spillover",
                "Spillover Temp", "Scatter Frac",
                "Scatter Temp")
        self.optics_band_cols = [2,3,9,11]
        self.optics_units = ('', '[K]', 'NA', 'NA', '[mm]', 'NA', '[e-4]', '[e6 S/m]', '[um RMS]', 'NA', '[K]', 'NA', '[K]')
        self.optics_stack = ('Primary', 'Secondary', 'Filter1', 'Filter2', 'Lyot', 'Filter3')
        self.det_titles =     ("Band ID", "Pixel ID",
                "Band Center", "Fractional BW",
                "Pixel Size", "Num Det per Wafer",
                "Num Waf per OT", "Num OT",
                "Waist Factor", "Det Eff",
                "Psat", "Psat Factor",
                "Carrier Index", "Tc",
                 "Tc Fraction", "Flink",
                 "Yield", "SQUID NEI",
                 "Bolo Resistance", "Read Noise Frac",
                 "G")
        self.det_units = ('', 'NA', '[GHz]', 'NA', '[mm]', 'NA', 'NA', 'NA', 'NA', 'NA', '[pW]', 'NA', 'NA', '[K]', 'NA', 'NA', 'NA', '[pA/rtHz]', '[Ohms]', 'NA', '[pW/K]')
        
    def write_bands(self):
        os.makedirs(self.bands_fp, exist_ok=True) 
        for j,band in enumerate(self.passbands):
            np.savetxt(f'{self.bands_fp}{self.cam}_{j+1}.txt', np.c_[self.freqs,band])
        
    def write_optics_heading(self, entries, units = False):
        row = []
        for j,entry in enumerate(entries):
            if j in self.optics_band_cols:
                row.append(f'{entry:<{7*self.N_bands}s}')
            else:
                row.append(f'{entry:<{16}s}')
        if units:
            row[0] = '#' + row[0][1:]
        return ' | '.join(row)

    def write_optics_row(self, optic):
        param_row = []
        for j,param in enumerate(self.optics_titles):
            if param in ['Absorption','Reflection','Spillover','Scatter Frac']:
                if isinstance(self.calc_optic(optic,param,self.band_centers[0]), str):
                    param_row.append(f'{"NA":<{7*self.N_bands}s}')
                    continue
                band_vals = []
                for nu in self.band_centers:
                    val = self.calc_optic(optic,param,nu)
                    band_vals.append(f'{val:>0.3f}')
                band_vals = ', '.join(band_vals)
                param_row.append(f'[{band_vals}]')
            elif param in ['Temperature']:
                val = self.calc_optic(optic,param)
                param_row.append(f'{val:>0.3f}{"":<{11}s}')
            elif param in ['Element']:
                param_row.append(f'{optic:<{16}s}')
            else:
                param_row.append(f'{"NA":<{16}s}')
        return ' | '.join(param_row)

    def write_optics_table(self):
        init_row = '#*****Optical Chain*****'
        title_row = self.write_optics_heading(self.optics_titles)
        unit_row = self.write_optics_heading(self.optics_units, units=True)
        lines = [init_row, title_row, unit_row]
        for optic in self.optics_stack:
            lines.append(self.write_optics_row(optic))
        with open(self.optics_fp, 'w') as f:
            for line in lines:
                f.write(f'{line}\n#{"-"*len(title_row)}\n')

    def calc_optic(self, optic, param, nu=150):
        temps = {'Primary': 4.0, 'Secondary': 4.0, 'Filter1': 3.9, 'Filter2': 1.0, 'Lyot': 1.0, 'Filter3': 0.1}
        absorbs = {'Primary': nu**1.1 * 1e-5, 'Secondary': nu**1.1 * 1e-5, 'Filter1': 0.01, 'Filter2': 0.01, 'Lyot': 'NA', 'Filter3': 0.01}
        reflects = {'Primary': 0.0, 'Secondary': 0.0, 'Filter1': 0.05, 'Filter2': 0.05, 'Lyot': 0.0, 'Filter3': 0.05}
        spills = {'Primary': 0.0, 'Secondary': 0.0, 'Filter1': 0.0, 'Filter2': 0.0, 'Lyot': 0.0, 'Filter3': 0.0}
        scatter = {'Primary': 0.0, 'Secondary': 0.0, 'Filter1': 0.0, 'Filter2': 0.0, 'Lyot': 0.0, 'Filter3': 0.0}
        if param == 'Absorption':
            return absorbs[optic]
        elif param == 'Reflection':
            return reflects[optic]
        elif param == 'Temperature':
            return temps[optic]
        elif param == 'Spillover':
            return spills[optic]
        elif param == 'Scatter Frac':
            return scatter[optic]
        else:
            print('wrong parameter!')
            return

    def write_det_heading(self, entries, units=False):
        row = []
        for j,entry in enumerate(entries):
            row.append(f'{entry:<{17}s}')
        if units:
            row[0] = '#' + row[0][1:]
        return ' | '.join(row)

    def write_det_row(self, band_id, nu, pixel_size):
        det_dict = {"Band ID":band_id, "Pixel ID": 1,
                    "Band Center": 'BAND', "Fractional BW": 'NA',
                    "Pixel Size": pixel_size, "Num Det per Wafer": 1,
                    "Num Waf per OT": 1, "Num OT": 1,
                    "Waist Factor": 3.0, "Det Eff": 'NA',
                    "Psat": 'NA', "Psat Factor": 3.0,
                    "Carrier Index": 2.7, "Tc": 0.159,
                     "Tc Fraction": 'NA', "Flink": 1.0,
                     "Yield": 1, "SQUID NEI": 45.0,
                     "Bolo Resistance": 0.004, "Read Noise Frac": 'NA',
                     "G": 'NA'}
        param_row = []
        for key,val in det_dict.items():
            if isinstance(val,str):
                param_row.append(f'{val:<{17}s}')
            elif isinstance(val,float):
                param_row.append(f'{val:>0.3f}{"":<{12}s}')
            elif isinstance(val,int):
                param_row.append(f'{val:<{17}d}')
        return ' | '.join(param_row)

    def write_det_table(self):
        init_row = '#*****Detector Channels*****'
        title_row = self.write_det_heading(self.det_titles)
        unit_row = self.write_det_heading(self.det_units, units=True)
        lines = [init_row, title_row, unit_row]
        for j,nu in enumerate(self.band_centers):
            lines.append(self.write_det_row(j+1, nu, self.pixel_sizes[j]))
        with open(self.channels_fp, 'w') as f:
            for line in lines:
                f.write(f'{line}\n#{"-"*len(title_row)}\n')

    def write_experiment(self):
        self.write_optics_table()
        self.write_det_table()
        self.write_bands()
        
    def calc_bolos(self):
        self.write_experiment()
        #!{' '.join(self.cmd_bolo)}
        run_cmd(' '.join(self.cmd_bolo))
        self.unpack.unpack_sensitivities(self.exp_fp)
        sens_arr = {}
        for j,band in enumerate(self.unpack.sens_outputs[self.exp][self.tel][self.cam]['All'].keys()):
            sens_arr[f'{j+1}'] = {}
            sens_arr[f'{j+1}']['Center Frequency [GHz]'] = self.band_centers[j]
            sens_arr[f'{j+1}']['NET_CMB [uK-rtSec]'] = self.unpack.sens_outputs[self.exp][self.tel][self.cam]['All'][band]['Detector NET_CMB'][0]
            sens_arr[f'{j+1}']['NET_RJ [uK-rtSec]'] = self.unpack.sens_outputs[self.exp][self.tel][self.cam]['All'][band]['Detector NET_RJ'][0]
            sens_arr[f'{j+1}']['Optical Power [pW]'] = self.unpack.sens_outputs[self.exp][self.tel][self.cam]['All'][band]['Optical Power'][0]
        return sens_arr
    
def run_cmd(cmd: str, stderr=subprocess.STDOUT) -> None:
    """Run a command in terminal

    Args:
        cmd (str): command to run in terminal
        stderr (subprocess, optional): Where the error has to go. Defaults to subprocess.STDOUT.

    Raises:
        e: Excetion of the CalledProcessError
    """
    out = None
    try:
        out = subprocess.check_output(
            [cmd],
            shell=True,
            stderr=stderr,
            universal_newlines=True,
        )
    except subprocess.CalledProcessError as e:
        print(f'ERROR {e.returncode}: {cmd}\n\t{e.output}',
              flush=True, file=sys.stderr)
        raise e
    print(out)