"""Classes for odorants, mixtures, chemical orders, etc."""

import base64
import io
import json
from datetime import datetime
from urllib.request import urlopen
from urllib.error import HTTPError
from urllib.parse import quote
import re

from IPython.display import display, Image
import numpy as np
import pubchempy as pcp
from PIL import Image
import quantities as pq
from quantities.constants.statisticalmechanics import R
import warnings

try:
    from rdkit import Chem
    from rdkit.Chem import Draw
except ImportError:
    warning.warn("Parts of rdkit could not be imported; try installing rdkit via conda",
                 "ImportWarning")
    
from pyrfume import ProgressBar
from pyrfume import load_data
from pyrfume.physics import mackay

ROOM_TEMP = (22 + 273.15) * pq.Kelvin
ROOM_PRESSURE = 1 * pq.atm
GAS_MOLAR_DENSITY = ROOM_PRESSURE / (R * ROOM_TEMP)

ODORANTS_BASIC_INFO_PATH = 'odorants/all-cids-properties.csv'


class Solution:
    def __init__(self, components, date_created=None):
        self.total_volume = 0 * pq.mL
        assert isinstance(components, dict), "Components must be a dict"
        for component, volume in components.items():
            assert isinstance(component, (Compound, Solution)), \
                "Each component must be a Compound or a Solution"
            try:
                volume = volume.rescale(pq.mL)
            except ValueError:
                raise ValueError("Components must be provided with volumes")
            self.total_volume += volume  # Assume that volume is conserved
        self.components = components
        self.date_created = date_created if date_created else datetime.now()

    @property
    def compounds(self):
        return self._compounds()

    def _compounds(self, result=None):
        if result is None:
            result = {}
        for component, volume in self.components.items():
            if isinstance(component, Compound):
                if component in result:
                    result[component] += volume
                else:
                    result[component] = volume
            else:  # If it is a Solution
                component._compounds(result=result)
        return result

    @property
    def molecules(self):
        """Returns a dictionary with the moles of each Molecule"""
        compounds = self.compounds
        assert all([c.density for c, v in compounds.items() if v
                    and not c.is_solvent]), \
            ("All non-solvent compounds must have a known density "
             "in order to compute moles")
        assert all([c.molecular_weight for c, v in compounds.items() if v
                    and not c.is_solvent]), \
            ("All non-solvent compounds must have a known molecular weight "
             "in order to compute moles")
        return {c.molecule: (v * c.molarity).rescale(pq.mol)
                for c, v in self.compounds.items() if v}

    @property
    def molarities(self):
        """Returns a dictionary with the molarity of each Molecule"""
        return {m: mol/self.total_volume
                for m, mol in self.molecules.items() if mol}

    @property
    def mole_fractions(self):
        """Returns a dictionary with the mole fraction of each Molecule"""
        molecules = self.molecules
        assert([moles for molecule, moles in molecules.items()]), \
            ("All compounds must have a known number of moles "
             "in order to compute mole fraction")
        # A Quantities bug prevents me from simply summing molecules.values()
        total_moles = 0 * pq.mol
        for moles in molecules.values():
            total_moles += moles
        return {molecule: moles/total_moles
                for molecule, moles in molecules.items()}

    def mole_fraction(self, molecule):
        return self.mole_fractions[molecule] \
               if molecule in self.mole_fractions else 0

    @property
    def dilutions(self):
        return {c.molecule: self.total_volume/c.volume
                for c in self.compounds if not c.is_solvent}

    @property
    def partial_pressures(self):
        """Computes partial pressures for each odorant
        in the mixture using Raoult's law"""
        return {m: self.mole_fraction(m)*m.vapor_pressure
                for m in self.molecules if m.vapor_pressure}

    def partial_pressure(self, molecule):
        return self.partial_pressures[molecule]

    @property
    def total_pressure(self):
        """Computes total pressure of the vapor using Dalton's law"""
        partial_pressures = self.partial_pressures.values()
        return sum(partial_pressures)

    @property
    def vapor_concentrations(self):
        """Concentrations of each component in the vapor phase at steady state.
        Units are fraction of volume. Air is assumed to make up the balance"""
        pp = self.partial_pressures
        result = {}
        for m, p in pp.items():
            ratio = (p/pq.atm).simplified
            assert ratio.units == pq.dimensionless
            result[m] = float(ratio)
        return result

    def vapor_concentration(self, molecule):
        return self.vapor_concentrations[molecule]

    @property
    def molar_evaporation_rates(self):
        mf = self.mole_fractions
        result = {molecule: mole_fraction*molecule.molar_evaporation_rate
                  for molecule, mole_fraction in mf.items()}
        return result


class Compound:
    def __init__(self, chemical_order, stock='',
                 date_arrived=None, date_opened=None, is_solvent=False):
        self.chemical_order = chemical_order
        self.date_arrived = date_arrived if date_arrived else datetime.now
        self.date_opened = date_opened
        self.is_solvent = is_solvent

    # ChemicalOrder
    chemical_order = None
    # Stock number (supplied by vendor, usually on bottle)
    stock = ''
    # Date arrived at the lab/clinic
    date_arrived = None
    # Date opened
    date_opened = None
    # Is it a solvent?
    is_solvent = False

    def __getattr__(self, attr):
        """If no attribute is found, try looking up on the
        ChemicalOrder or the Molecule"""
        try:
            return getattr(self.chemical_order, attr)
        except AttributeError:
            return getattr(self.chemical_order.molecule, attr)


class ChemicalOrder:
    def __init__(self, molecule, vendor, part_id,
                 purity=1, known_impurities=None):
        self.molecule = molecule
        self.vendor = vendor
        self.part_id = part_id
        self.purity = purity
        self.known_impurities = known_impurities

    # Molecule
    molecule = None
    # Vendor, e.g. Sigma-Aldrich
    vendor = None
    # ID number of compound at vendor
    part_id = ''
    # Reported purity as a fraction
    purity = 1
    # List of known impurities (Molecules)
    known_impurities = None


class Vendor:
    def __init__(self, name, url):
        self.name = name
        self.url = url

    name = ''
    url = ''


class Molecule:
    def __init__(self, cid, name=None, fill=False):
        self.cid = cid
        if fill:
            self.fill_details()
        if name:
            self.name = name

    # Integer Chemical ID number (CID) from PubChem
    cid = 0
    # Chemical Abstract Service (CAS) number
    cas = ''
    # Principal name
    name = ''
    # Synonyms
    synonyms = ''
    # IUPAC name (long, unique name)
    iupac = ''
    # Density (pq.g / pq.ml)
    density = None
    # Vapor pressure (pq.Pa)
    vapor_pressure = None
    # Molecular weight (pq.g / pq.mol)
    molecular_weight = None

    @property
    def molarity(self):
        if not self.molecular_weight:
            result = None
        else:
            result = self.density / self.molecular_weight
            result = result.rescale(pq.mol / pq.L)
        return result

    @property
    def molar_evaporation_rate(self):
        return mackay(self.vapor_pressure)

    def fill_details(self):
        assert self.cid is not None
        url_template = ("https://pubchem.ncbi.nlm.nih.gov/"
                        "rest/pug/compound/cid/%d/property/"
                        "%s/JSON")
        property_list = ['MolecularWeight', 'IsomericSMILES']
        url = url_template % (self.cid, ','.join(property_list))
        json_data = url_to_json(url)
        details = json_data['PropertyTable']['Properties'][0]

        def convert(name):
            s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
            return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()

        for key, value in details.items():
            if key == 'CID':
                assert value == self.cid, \
                    "REST API CID does not match provided CID"
            key = convert(key)
            if key == 'molecular_weight':
                value *= pq.g / pq.mol
            setattr(self, key, value)

        if not self.name:
            self.name = self.get_name_from_api()

    def get_name_from_api(self):
        url_template = ("https://pubchem.ncbi.nlm.nih.gov/"
                        "rest/pug/compound/cid/%d/synonyms/JSON")
        url = url_template % (self.cid)
        json_data = url_to_json(url)
        name = None
        if json_data:
            information = json_data['InformationList']['Information'][0]
            synonyms = information['Synonym']
            name = synonyms[0].lower()
        return name

    def get_cid_from_api(self):
        url_template = ("https://pubchem.ncbi.nlm.nih.gov/"
                        "rest/pug/compound/%s/%s/cids/JSON")
        options = [getattr(self, x) for x in ('cas', 'name')
                   if len(getattr(self, x))]
        cid = None
        query = self.name
        for option in options:
            url = url_template % (option, query)
            json_data = url_to_json(url)
        cid = json_data['IdentifierList']['CID'][0]
        return cid

    def __eq__(self, other):
        if self.cid:
            return self.cid == other.cid
        else:
            return self.name == self.name
        
    def __lt__(self, other):
        if self.cid:
            return self.cid < other.cid
        else:
            return self.name < self.name

    def __hash__(self):
        return id(self)

    def __repr__(self):
        if self.cid and self.name:
            result = '%d (%s)' % (self.cid, self.name)
        elif self.cid:
            result = '%d' % self.cid
        elif self.name:
            result = '%s' % self.name
        else:
            result = 'Unknown'
        return result


def url_to_json(url, verbose=True):
    json_data = None
    msgs = []
    try:
        page = urlopen(url)
        string = page.read().decode('utf-8')
        json_data = json.loads(string)
    except HTTPError:
        msgs.append("HTTPError for query '%s'" % url)
    if json_data is None and verbose:
        for msg in msgs:
            print(msg)
    return json_data


def canonical_smiles(smiles, kekulize=False):
    """Use rdkit to convert the `smiles` string to canonical form"""
    mol = Chem.MolFromSmiles(smiles)
    if mol: # If a mol object was successfully create (i.e. not `None`)
        if kekulize:
            Chem.Kekulize(mol)
        smiles = Chem.MolToSmiles(mol, isomericSmiles=True)
    else: # No mol object means the `smiles` string was invalid
        smiles = ''
    return smiles


def get_cids(identifiers, kind='name', verbose=True):
    """Return CIDs for molecule based on any synonym,
    including a chemical name or a CAS"""
    kind = kind.lower()
    results = {}
    p = ProgressBar(len(identifiers))
    for i, identifier in enumerate(identifiers):
        p.animate(i, status=identifier)
        cid = get_cid(identifier, kind=kind, verbose=verbose)
        if not cid:
            p.log("Could not find %s" % identifier)
        results[identifier] = cid
    p.report()
    return results


def get_cid(identifier, kind='name', verbose=True, fix_smiles_on_error=True):
    """Return data about a molecule from any synonym,
    including a chemical name or a CAS"""
    kind=kind.lower()
    try:
        result = pcp.get_cids(identifier, namespace=kind)
    except pcp.BadRequestError:
        print('Request Error for "%s"' % identifier)
        result = []
    if not len(result):
        cid = 0
    else:
        if (len(result) > 1) and verbose:
            print("Multiple CIDs for %s: %s" %
                  (identifier, result))
        cid = result[0]
    if not cid and kind == 'smiles' and fix_smiles_on_error:
        # Retry with canonical SMILES
        identifier = canonical_smiles(identifier)
        if identifier:
            cid = get_cid(identifier, kind=kind, verbose=verbose, fix_smiles_on_error=False)
    return cid

    """
    # DEPRECATED
    # Try as a compound
    url_template = ("https://pubchem.ncbi.nlm.nih.gov/"
                    "rest/pug/compound/%s/%s/property/"
                    "isomericsmiles,iupacname,molecularweight,/JSON")
    url = url_template % (kind, identifier)
    json_data = url_to_json(url, verbose=verbose)
    result = {}
    if json_data:
        result = json_data['PropertyTable']['Properties'][0]
    else:  # Try again as a substance
        url_template = ("https://pubchem.ncbi.nlm.nih.gov/"
                        "rest/pug/substance/%s/%s/cids/json?"
                        "list_return=flat")
        url = url_template % (kind, identifier)
        json_data = url_to_json(url, verbose=verbose)
        if json_data:
            cids = json_data['IdentifierList']['CID']
            if cids and verbose:
                print("Substance %s has CIDs: " % identifier, cids)
            cid_results = from_cids(cids)
            result = cid_results[0]
    """
    return result


def from_cids(cids, property_list=None):
    if property_list is None:
        property_list = ['MolecularWeight', 'IsomericSMILES', 'IUPACName']
    result = []
    chunk_size = 100
    p = ProgressBar(len(cids))
    for start in range(0, len(cids), chunk_size):
        stop = min(start + chunk_size, len(cids))
        msg = "Retrieving %d through %d" % (start, stop-1)
        p.animate(start, status=msg)
        cid_subset = [str(x) for x in [cid for cid in cids[start:stop] if int(cid)>0 and cid is not None]]
        cid_subset = ','.join(cid_subset)
        properties_template = ("https://pubchem.ncbi.nlm.nih.gov/"
                               "rest/pug/compound/cid/%s/property/"
                               "%s/JSON")
        url = properties_template % (cid_subset, ','.join(property_list))
        json_data = url_to_json(url)
        data = json_data['PropertyTable']['Properties']

        synonyms_template = ("https://pubchem.ncbi.nlm.nih.gov/"
                             "rest/pug/compound/cid/%s/synonyms/JSON")
        url = synonyms_template % (cid_subset)
        json_data = url_to_json(url)
        information = json_data['InformationList']['Information']
        for i, d in enumerate(data):
            try:
                synonyms = information[i]['Synonym']
            except KeyError:
                try:
                    d['name'] = d['IUPACName']
                except KeyError:
                    d['name'] = ''
            else:
                d['name'] = synonyms[0].lower()
        result += data
        msg = "Retrieved %d through %d" % (start, stop-1)
        p.animate(stop, status=msg)
    return result


def cids_to_cas(cids):
    result = {}
    chunk_size = 100
    p = ProgressBar(len(cids))
    for start in range(0, len(cids), chunk_size):
        stop = min(start + chunk_size, len(cids))
        msg = "Retrieving %d through %d" % (start, stop-1)
        p.animate(start, status=msg)
        cid_subset = [str(x) for x in cids[start:stop]]
        cid_subset = ','.join(cid_subset)
        synonyms_template = ("https://pubchem.ncbi.nlm.nih.gov/"
                             "rest/pug/compound/cid/%s/synonyms/JSON")
        url = synonyms_template % (cid_subset)
        json_data = url_to_json(url)
        information = json_data['InformationList']['Information']
        for i, info in enumerate(information):
            cid = info['CID']
            try:
                synonyms = info['Synonym']
            except KeyError:
                result[cid] = []
            else:
                result[cid] = cas_from_synonyms(synonyms)
        result
    return result


def cas_from_synonyms(synonyms):
    result = []
    for s in synonyms:
        if re.match('^[0-9]+\-[0-9]+\-[0-9]+$', s):
            result.append(s)
    return result

            
def cactus(identifier, output='cas'):
    url_template = "https://cactus.nci.nih.gov/chemical/structure/%s/%s"
    url = url_template % (identifier, output)
    page = urlopen(url)
    result = page.read().decode('utf-8')
    return result


def cactus_image(smiles):
    url_template = "https://cactus.nci.nih.gov/chemical/structure/%s/image"
    url = url_template % smiles
    image_data = urlopen(url).read()
    image = Image(image_data)
    display(image)


def get_compound_summary(cid, heading):
    """Get summary info about `heading` from PubChem for the compound
    given by `cid`.  Example heading: 'Physical Description'"""
    url_template = ("https://pubchem.ncbi.nlm.nih.gov/"
                    "rest/pug_view/data/compound/%d/JSON?heading=%s")
    escaped_heading = quote(heading)  # Escape the string
    url = url_template % (cid, escaped_heading)
    json_data = url_to_json(url, verbose=False)
    return json_data


def get_compound_odor(cid, raw=False):
    info = []
    for heading in ['Odor', 'Physical Description']:
        json_data = get_compound_summary(cid, heading)
        if raw:
            info += [] if json_data is None else [json_data]
        else:
            info += _parse_odor_info(json_data)
    return info


def _parse_odor_info(info, odors=None, any_string=False):
    if odors is None:
        odors = []
    if isinstance(info, dict):
        for key, value in info.items():
            if key == 'TOCHeading' and value == 'Odor':
                any_string = True
            if key == 'String' and (any_string or 'odor' in value.lower()):
                odors.append(value)
            else:
                _parse_odor_info(value, odors=odors, any_string=any_string)
    elif isinstance(info, list):
        for value in info:
            _parse_odor_info(value, odors=odors, any_string=any_string)
    return odors


def _parse_other_info(info, records=None):
    if records is None:
        records = []
    if isinstance(info, dict):
        for key, value in info.items():
            if key == 'String':
                records.append(value)
            elif key == 'Value' and 'Number' in value:
                records.append(value)
            else:
                _parse_other_info(value, records=records)
    elif isinstance(info, list):
        for value in info:
            _parse_other_info(value, records=records)
    return records


def smiles_to_image(smiles, png=True, b64=False, crop=True, padding=10, size=300):
    """
    png: Whether to convert to .png data (or to leave as a PIL image)
    b64: Whether to base64 encode (only possible for .png data)
    """
    buffer = io.BytesIO()
    mol = Chem.MolFromSmiles(smiles)
    image = Draw.MolToImage(mol, fitImage=True, size=(size, size))
    if crop:
        image = crop_image(image, padding=padding)
    if png:
        image.save(buffer, format='PNG')
        image = buffer.getvalue()
    if b64:
        assert png, "Can only base64 encode PNG data, not a PIL image"
        image = base64.b64encode(image).decode('utf8')
    return image


def crop_image(img, padding=0):
    """Crop white out of a PIL image."""
    as_array = np.array(img)  # N x N x (r,g,b,a)
    if as_array.shape[2] == 4:
        as_array[as_array[:, :, 3] == 0] = [255, 255, 255, 255]
    has_content = np.sum(as_array, axis=2, dtype=np.uint32) != 255 * 4
    xs, ys = np.nonzero(has_content)
    x_range = max([min(xs) - padding, 0]), min([max(xs) + padding, as_array.shape[0]])
    y_range = max([min(ys) - padding, 0]), min([max(ys) + padding, as_array.shape[1]])
    as_array_cropped = as_array[
        x_range[0]:x_range[1], y_range[0]:y_range[1], 0:3]
    img = Image.fromarray(as_array_cropped, mode='RGB')
    return img


def all_odorants():
    """All CIDs, SMILES, Names, and Molecular Weights found in the
    file at ODORANTS_BASIC_INFO_PATH"""
    df = load_data(ODORANTS_BASIC_INFO_PATH)
    df = df.sort_index()
    return df


def all_cids():
    """All CIDs found in the file at ODORANTS_BASIC_INFO_PATH"""
    df = all_odorants()
    return list(df.index)


def all_smiles():
    """All SMILES found in the file at ODORANTS_BASIC_INFO_PATH"""
    df = all_odorants()
    return list(df['SMILES'])


if __name__ == '__main__':
    x = Molecule(325, fill=True)
    print(x.__dict__)
