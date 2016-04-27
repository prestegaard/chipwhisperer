#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Copyright (c) 2014, NewAE Technology Inc
# All rights reserved.
#
# Authors: Colin O'Flynn
#
# Find this and more at newae.com - this file is part of the chipwhisperer
# project, http://www.assembla.com/spaces/chipwhisperer
#
#    This file is part of chipwhisperer.
#
#    chipwhisperer is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    chipwhisperer is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Lesser General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with chipwhisperer.  If not, see <http://www.gnu.org/licenses/>.
#
# ChipWhisperer is a trademark of NewAE Technology Inc.
#============================================================================

import numpy as np
import scipy
from chipwhisperer.common.api.config_parameter import ConfigParameter
from chipwhisperer.common.api.autoscript import AutoScript
from ._stats import DataTypeDiffs
from chipwhisperer.analyzer.attacks.models.AES128_8bit import getHW
import chipwhisperer.analyzer.attacks.models.AES128_8bit as AESModel
from chipwhisperer.common.utils import util
try:
    from scipy.stats import multivariate_normal
except ImportError:
    multivariate_normal = None


class TemplateBasic(AutoScript):
    """
    Template using Multivariate Stats (mean + covariance matrix)
    """
    scriptsUpdated = util.Signal()

    def __init__(self):
        super(TemplateBasic, self).__init__()
        self._traceSource = None

    def traceSource(self):
        return self._traceSource

    def setTraceSource(self, trace):
        self._traceSource = trace

    def setProject(self, proj):
        self._project = proj

    def project(self):
        return self._project

    def generate(self, trange, poiList, partMethod, progressBar=None):
        """Generate templates for all partitions over entire trace range"""

        # Number of subkeys
        subkeys = len(poiList)

        numPartitions = partMethod.getNumPartitions()

        tstart = trange[0]
        tend = trange[1]

        templateTraces = [ [ [] for j in range(0, numPartitions) ] for i in range(0, subkeys) ]

        templateMeans = [ np.zeros((numPartitions, len(poiList[i]))) for i in range (0, subkeys) ]
        templateCovs = [ np.zeros((numPartitions, len(poiList[i]), len(poiList[i]))) for i in range (0, subkeys) ]

        # partData = generatePartitions(self, partitionClass=None, saveFile=False, loadFile=False, traces=None)
        # partData = partObj.loadPartitions(trange)

        if progressBar:
            progressBar.setText('Generating Trace Matrix:')
            progressBar.setMaximum(tend - tstart + subkeys)

        for tnum in range(tstart, tend):
            # partData = self.traceSource().getAuxData(tnum, self.partObject.attrDictPartition)["filedata"]
            pnum = partMethod.getPartitionNum(self.traceSource(), tnum)
            t = self.traceSource().getTrace(tnum)
            for bnum in range(0, subkeys):
                templateTraces[bnum][pnum[bnum]].append(t[poiList[bnum]])

            if progressBar:
                progressBar.updateStatus(tnum - tstart)
                if progressBar.wasAborted():
                    return None

        if progressBar:
            progressBar.setText('Generating Trace Covariance and Mean Matrices:')

        for bnum in range(0, subkeys):
            for i in range(0, numPartitions):
                templateMeans[bnum][i] = np.mean(templateTraces[bnum][i], axis=0)
                cov = np.cov(templateTraces[bnum][i], rowvar=0)
                # print "templateTraces[%d][%d] = %d" % (bnum, i, len(templateTraces[bnum][i]))

                if len(templateTraces[bnum][i]) > 0:
                    templateCovs[bnum][i] = cov
                else:
                    print "WARNING: Insufficient template data to generate covariance matrix for bnum=%d, partition=%d" % (bnum, i)
                    templateCovs[bnum][i] = np.zeros((len(poiList[bnum]), len(poiList[bnum])))

            if progressBar:
                progressBar.updateStatus(tend + bnum)
                if progressBar.wasAborted():
                    return None

                # except ValueError:
                #    raise ValueError("Insufficient template data to generate covariance matrix for bnum=%d, partition=%d" % (bnum, i))

        # self.templateMeans = templateMeans
        # self.templateCovs = templateCovs
        # self.templateSource = (tstart, tend)
        # self.templatePoiList = poiList
        # self.templatePartMethod = partMethod

        self.template = {
         "mean":templateMeans,
         "cov":templateCovs,
         "trange":(tstart, tend),
         "poi":poiList,
         "partitiontype":partMethod.__class__.__name__
        }

        if progressBar:
            progressBar.close()

        return self.template


class ProfilingTemplate(AutoScript):
    """
    Template Attack done as a loop, but using an algorithm which can progressively add traces & give output stats
    """
    paramListUpdated = util.Signal()
    notifyUser = util.Signal()

    def __init__(self, parent):
        AutoScript.__init__(self)
        self.parent = parent
        self._traceSource = None
        self._project = None

        resultsParams = [{'name':'Load Template', 'type':'group', 'children':[
                            ]},
                         {'name':'Generate New Template', 'type':'group', 'children':[
                            {'name':'Trace Start', 'key':'tgenstart', 'value':0, 'type':'int', 'set':self.updateScript},
                            {'name':'Trace End', 'key':'tgenstop', 'value':self.parent.traceMax, 'type':'int', 'set':self.updateScript},
                            {'name':'POI Selection', 'key':'poimode', 'type':'list', 'values':{'TraceExplorer Table':0, 'Read from Project File':1}, 'value':0, 'set':self.updateScript},
                            {'name':'Read POI', 'type':'action', 'action':self.updateScript},
                            {'name':'Generate Templates', 'type':'action', 'action': lambda:self.runScriptFunction.emit("generateTemplates")}
                            ]},
                         ]
        self.params = ConfigParameter.create_extended(self, name='Template Attack', type='group', children=resultsParams)

        self.addGroup("generateTemplates")

        self.sr = None

        self.stats = DataTypeDiffs()
        self.setProfileAlgorithm(TemplateBasic)

        # Not needed as setProfileAlgorithm calls this
        # self.updateScript()

    def setProfileAlgorithm(self, algo):
        self.profiling = algo()
        self.profiling.setTraceSource(self._traceSource)
        self.profiling.setProject(self._project)
        self.profiling.scriptsUpdated.connect(self.updateScript)
        self.updateScript()

    def updateScript(self, ignored=None):
        pass
       # self.addFunction('init', 'setReportingInterval', '%d' % self.findParam('reportinterval').value())
       #
       #  ted = self.parent.traceExplorerDialog.exampleScripts[0]
       #
       #  self.addFunction('generateTemplates', 'initAnalysis', '', obj='UserScript')
       #  self.addVariable('generateTemplates', 'tRange', '(%d, %d)' % (self.findParam('tgenstart').value(), self.findParam('tgenstop').value()))
       #
       #  if self.findParam('poimode').value() == 0:
       #      self.addVariable('generateTemplates', 'poiList', '%s' % ted.poi.poiArray)
       #      self.addVariable('generateTemplates', 'partMethod', '%s()' % ted.partObject.partMethod.__class__.__name__)
       #      self.importsAppend("from chipwhisperer.analyzer.utils.Partition import %s" % ted.partObject.partMethod.__class__.__name__)
       #  else:
       #      poidata = self.loadPOIs()[-1]
       #      self.addVariable('generateTemplates', 'poiList', '%s' % poidata["poi"])
       #      self.addVariable('generateTemplates', 'partMethod', '%s()' % poidata["partitiontype"])
       #      self.importsAppend("from chipwhisperer.analyzer.utils.Partition import %s" % poidata["partitiontype"])
       #
       #  self.addFunction('generateTemplates', 'profiling.generate', 'tRange, poiList, partMethod', 'templatedata')
       #
       #  #Save template data to project
       #  self.addFunction('generateTemplates', 'saveTemplatesToProject', 'tRange, templatedata', 'tfname')
       #
       #  self.scriptsUpdated.emit()

    def paramList(self):
        return [self.params]

    def traceLimitsChanged(self, traces, points):
        tstart = self.findParam('tgenstart')
        tend = self.findParam('tgenstop')
        tstart.setLimits((0, traces))
        tend.setValue(traces)
        tend.setLimits((1, traces))

    def setByteList(self, brange):
        self.brange = brange

    def setKeyround(self, keyround):
        self.keyround = keyround

    def setReportingInterval(self, intv):
        self._reportinginterval = intv

    def traceSource(self):
        return self._traceSource

    def setTraceManager(self, tmanager):
        self._traceSource = tmanager
        # Set for children
        self.profiling.setTraceManager(tmanager)

    def setProject(self, proj):
        self._project = proj
        # Set for children
        self.profiling.setProject(proj)

    def project(self):
        if self._project is None:
            self.setProject(self.parent().project())
        return self._project

    def saveTemplatesToProject(self, trange, templatedata):
        cfgsec = self.project().addDataConfig(sectionName="Template Data", subsectionName="Templates")
        cfgsec["tracestart"] = trange[0]
        cfgsec["traceend"] = trange[1]
        cfgsec["poi"] = templatedata["poi"]
        cfgsec["partitiontype"] = templatedata["partitiontype"]

        fname = self.project().getDataFilepath('templates-%s-%d-%d.npz' % (cfgsec["partitiontype"], trange[0], trange[1]), 'analysis')

        # Save template file
        np.savez(fname["abs"], **templatedata)  # mean=self.profiling.templateMeans, cov=self.profiling.templateCovs)
        cfgsec["filename"] = fname["rel"]

        print "Saved template to: %s" % fname["abs"]

        return fname["abs"]

    def loadTemplatesFromProject(self):
        # Load Template
        foundsecs = self.parent().project().getDataConfig(sectionName="Template Data", subsectionName="Templates")
        templates = []

        for f in foundsecs:
            fname = self.parent().project().convertDataFilepathAbs(f["filename"])
            t = np.load(fname)
            templates.append(t)

            # Validate in case someone tries to change via project file
            if f["partitiontype"] != t["partitiontype"]:
                print "WARNING: PartitionType for template from .npz file (%s) differs from project file (%s). npz file being used."

            if (util.strListToList(str(f["poi"])) != t["poi"]).any():
                print "WARNING: POI for template from .npz file (%s) differs from project file (%s). npz file being used."

        return templates

    def loadPOIs(self):
        section = self.project().getDataConfig("Template Data", "Points of Interest")

        poiList = []

        for s in section:
            poistr = str(s["poi"])
            poieval = util.strListToList(poistr)
            poiList.append(s.copy())
            poiList[-1]["poi"] = poieval

        return poiList

    def addTraces(self, traces, plaintexts, ciphertexts, knownkeys=None, progressBar=None, pointRange=None):

        if multivariate_normal is None:
            print "ERROR: Version of SciPy too old, require > 0.14, have %s" % (scipy.version.version)
            print "       Please update your version of SciPy to support this attack"
            return

        # Hack for now - just use last template found
        template = self.loadTemplatesFromProject()[-1]
        pois = template["poi"]
        numparts = len(template['mean'][0])
        results = np.zeros((16, 256))

        tdiff = self._reportinginterval

        if progressBar:
            progressBar.setStatusMask("Current Trace = %d-%d Current Subkey = %d")
            progressBar.setMaximum(16 * len(traces))
        pcnt = 0

        for tnum in range(0, len(traces)):
            for bnum in range(0, 16):
                newresultsint = [multivariate_normal.logpdf(traces[tnum][pois[bnum]], mean=template['mean'][bnum][i], cov=np.diag(template['cov'][bnum][i])) for i in range(0, numparts)]

                ptype = template["partitiontype"]

                if ptype == "PartitionHWIntermediate":
                    newresults = []
                    # Map to key guess format
                    for i in range(0, 256):
                        # Get hypothetical hamming weight
                        # hypint = HypHW(plaintexts[tnum], None, i, bnum)
                        hypint = AESModel.leakage(plaintexts[tnum], ciphertexts[tnum], i, bnum, AESModel.LEAK_HW_SBOXOUT_FIRSTROUND, None)
                        newresults.append(newresultsint[ hypint ])
                elif ptype == "PartitionHDLastRound":
                    newresults = []
                    # Map to key guess format
                    for i in range(0, 256):
                        # Get hypothetical hamming distance
                        # hypint = HypHD(plaintexts[tnum], None, i, bnum)
                        # hypint = HypHD(None, ciphertexts[tnum], i, bnum)
                        hypint = AESModel.leakage(plaintexts[tnum], ciphertexts[tnum], i, bnum, AESModel.LEAK_HD_LASTROUND_STATE, None)
                        newresults.append(newresultsint[ hypint ])

                # TODO Temp
                elif ptype == "PartitionHDRounds":
                    newresults = []
                    # Map to key guess format
                    for i in range(0, 256):
                        # Get hypothetical hamming distance
                        # hypint = HypHD(plaintexts[tnum], None, i, bnum)
                        if bnum == 0:
                            hypint = getHW(plaintexts[tnum][bnum] ^ i)
                        else:
                            knownkey = [0x2b, 0x7e, 0x15, 0x16, 0x28, 0xae, 0xd2, 0xa6, 0xab, 0xf7, 0x15, 0x88, 0x09, 0xcf, 0x4f, 0x3c]
                            s1 = plaintexts[tnum][bnum - 1] ^ knownkey[bnum - 1]
                            s2 = plaintexts[tnum][bnum] ^ i
                            hypint = getHW(s1 ^ s2)

                        newresults.append(newresultsint[ hypint ])
                else:
                    newresults = newresultsint

                results[bnum] += newresults
                self.stats.updateSubkey(bnum, results[bnum], tnum=(tnum + 1))

                if progressBar:
                    progressBar.updateStatus(pcnt, (tnum, len(traces)-1, bnum))
                    if progressBar.wasAborted():
                        return
                pcnt += 1

            # Do plotting if required
            if (tnum % tdiff) == 0 and self.sr:
                self.sr()

    def getStatistics(self):
        return self.stats

    def setStatsReadyCallback(self, sr):
        self.sr = sr
